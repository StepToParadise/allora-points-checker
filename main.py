import os
import requests
import json
import time
import random
import brotli
import argparse
from datetime import datetime
from glob import glob
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import cycle

def decompress_response(response):
    try:
        content_encoding = response.headers.get('Content-Encoding', '')
        content_type = response.headers.get('Content-Type', '')

        if 'application/json' in content_type:
            return response.content

        if 'br' in content_encoding:
            return brotli.decompress(response.content)
        elif 'gzip' in content_encoding:
            return zlib.decompress(response.content, 16 + zlib.MAX_WBITS)
        elif 'deflate' in content_encoding:
            return zlib.decompress(response.content)
        else:
            print("No compression detected")
            return response.content
        
    except Exception as e:
        print(f"Error during decompression: {e}")
        print(f"Raw response content (first 100 bytes): {response.content[:100]}")
        with open('problematic_response.bin', 'wb') as f:
            f.write(response.content)
        return None

def read_wallets(filepath):
    with open(filepath, 'r') as file:
        return [line.strip() for line in file.readlines()]

def read_proxies(filepath):
    with open(filepath, 'r') as file:
        return [f"http://{line.strip()}" for line in file.readlines()]

def send_post_request(wallet, headers, url, proxy_cycle, retries=10):
    if wallet.startswith("0x"):
        payload = {"allora_address": None, "evm_address": wallet}
    else:
        payload = {"allora_address": wallet, "evm_address": None}

    attempt = 0
    while attempt < retries:
        try:
            proxy = next(proxy_cycle, None)
            proxies = {"http": proxy, "https": proxy} if proxy else None
            response = requests.post(url, headers=headers, json=payload, proxies=proxies)
            if response.status_code in {403, 500, 502, 503}:
                attempt += 1
                continue
            response.raise_for_status()
            return response.json() if response.text else None
        except requests.exceptions.RequestException:
            attempt += 1

    print(f"Failed to process wallet {wallet} after {retries} attempts")    
    return None

def send_get_request(data_id, headers, url, proxy_cycle, retries=10):
    attempt = 0
    while attempt < retries:
        try:
            proxy = next(proxy_cycle, None)
            proxies = {"http": proxy, "https": proxy} if proxy else None
            response = requests.get(url.format(id=data_id), headers=headers, proxies=proxies)
            
            if response.status_code in {403, 500, 502, 503}:
                attempt += 1
                continue
            response.raise_for_status()

            content_type = response.headers.get('Content-Type', '')
            if 'application/json' in content_type:
                decompressed_content = decompress_response(response)
                if decompressed_content:
                    decompressed_text = decompressed_content.decode('utf-8')
                    return json.loads(decompressed_text)
                else:
                    print(f"Failed to decompress content for ID: {data_id}")
            else:
                print(f"Unexpected content type for ID: {data_id}, response: {response.content}")
            return None
                        
        except requests.exceptions.RequestException:
            attempt += 1
        except json.JSONDecodeError as json_err:
            attempt += 1
        except Exception as err:
            attempt += 1

    return None

def log_result(wallet, data_id, points, rank, log_filename):
    with open(log_filename, 'a') as file:
        file.write(f"Wallet: {wallet} | ID: {data_id} | Points: {points} | Rank: {rank}\n")

def get_last_two_logs(directory, pattern="result_*.log"):
    try:
        log_files = glob(os.path.join(directory, pattern))
        log_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        if len(log_files) >= 2:
            return log_files[1], log_files[0]
        else:
            print("Not enough logs to compare")
            return None, None
        
    except Exception as e:
        print(f"Error trying read logs: {e}")
        return None, None

def read_wallets_data(filename):
    wallets = []
    with open(filename, "r") as f:
        raw_data = f.readlines()
    
    for entry in raw_data:
        entry = entry.strip()
        if entry:
            parts = entry.split(" | ")
            if len(parts) >= 4:
                try:
                    wallet_info = {
                        "Wallet": parts[0].split(": ")[1],
                        "Points": float(parts[2].split(": ")[1]) if "No data" not in parts[2] else 0,
                        "Rank": int(parts[3].split(": ")[1]) if "No data" not in parts[3] else 0,
                    }
                    wallets.append(wallet_info)

                except (IndexError, ValueError) as e:
                    print(f"Error parsing line: {entry}, code: {e}")
            else:
                print(f"Invalid line: {entry}")
    return wallets

def process_wallet(wallet, headers_post, headers_get, url_post, url_get, log_filename, proxy_cycle):
    post_response = send_post_request(wallet, headers_post, url_post, proxy_cycle)
    if post_response and post_response.get("status"):
        data_id = post_response.get("data", {}).get("id")
        if data_id:
            get_response = send_get_request(data_id, headers_get, url_get, proxy_cycle)
            if get_response and get_response.get("status"):
                try:
                    if wallet.startswith("0x"):
                        points = get_response.get("data", {}).get("evm_leaderboard_stats", {}).get("total_points", 0)
                        rank = get_response.get("data", {}).get("evm_leaderboard_stats", {}).get("rank", "N/A")
                    else:
                        points = get_response.get("data", {}).get("allora_leaderboard_stats", {}).get("total_points", 0)
                        rank = get_response.get("data", {}).get("allora_leaderboard_stats", {}).get("rank", "N/A")
                    
                    print(f"Wallet: {wallet} | ID: {data_id} | Points: {points} | Rank: {rank}")
                    log_result(wallet, data_id, points, rank, log_filename)
               
                except AttributeError:
                    print(f"Wallet: {wallet} | No data")

def calculate_totals(wallets):
    total_points = 0
    wallets_with_points = 0
    
    for wallet in wallets:
        total_points += wallet["Points"]
        if wallet["Points"] > 0:
            wallets_with_points += 1
    
    return total_points, wallets_with_points

def count_wallets_by_points(wallets):
    categories = {
        "0.000001 - 1": 0,
        "1 - 10": 0,
        "10 - 50": 0,
        "50 - 100": 0,
        "100 - 500": 0,
    }
    
    for wallet in wallets:
        points = wallet["Points"]
        if 0.000001 <= points < 1:
            categories["0.000001 - 1"] += 1
        elif 1 <= points < 10:
            categories["1 - 10"] += 1
        elif 10 <= points < 50:
            categories["10 - 50"] += 1
        elif 50 <= points < 100:
            categories["50 - 100"] += 1
        elif 100 <= points < 500:
            categories["100 - 500"] += 1
    
    return categories

def count_wallets_by_rank(wallets):
    rank_categories = {
        "1 - 5000": 0,
        "5001 - 15 000": 0,
        "15 001 - 30 000": 0,
        "30 001 - 50 000": 0,
        "50 001 - 100 000": 0,
        "100 001 - 1 000 000": 0,
    }
    
    for wallet in wallets:
        rank = wallet["Rank"]
        if 1 <= rank <= 5000:
            rank_categories["1 - 5000"] += 1
        elif 5001 <= rank <= 15000:
            rank_categories["5001 - 15 000"] += 1
        elif 15001 <= rank <= 30000:
            rank_categories["15 001 - 30 000"] += 1
        elif 30001 <= rank <= 50000:
            rank_categories["30 001 - 50 000"] += 1
        elif 50001 <= rank <= 100000:
            rank_categories["50 001 - 100 000"] += 1
        elif 100001 <= rank <= 1000000:
            rank_categories["100 001 - 1 000 000"] += 1
    
    return rank_categories

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--threads', type=int, default=50, help="Number of threads to use")
    args = parser.parse_args()

    url_post = "https://api.upshot.xyz/v2/allora/users/connect"
    url_get = "https://api.upshot.xyz/v2/allora/points/{id}"
    headers_post = {
        "accept": "application/json, text/plain, */*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "content-type": "application/json",
        "dnt": "1",
        "origin": "https://app.allora.network",
        "referer": "https://app.allora.network/",
        "user-agent": "Mozilla/5.0",
        "x-api-key": "UP-0d9ed54694abdac60fd23b74"
    }

    headers_get = headers_post.copy()
    headers_get["if-none-match"] = 'W/"180-wWc9Nj5jKOz4m2gZtCQbgGkX8dg"'

    wallets = read_wallets('wallets.txt')
    proxies = read_proxies('proxies.txt')
    proxy_cycle = cycle(proxies)

    log_filename = datetime.now().strftime("result_%d-%m-%y-%Hx%M.log")

    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        futures = [executor.submit(process_wallet, wallet, headers_post, headers_get, url_post, url_get, log_filename, proxy_cycle) for wallet in wallets]
        for future in as_completed(futures):
            future.result()
    
    previous_log, latest_log = get_last_two_logs(".")
    if previous_log and latest_log:
        previous_wallets_data = read_wallets_data(previous_log)
        current_wallets_data = read_wallets_data(latest_log)

        previous_total_points, previous_wallets_with_points = calculate_totals(previous_wallets_data)
        current_total_points, current_wallets_with_points = calculate_totals(current_wallets_data)

        previous_categories = count_wallets_by_points(previous_wallets_data)
        current_categories = count_wallets_by_points(current_wallets_data)

        previous_rank_categories = count_wallets_by_rank(previous_wallets_data)
        current_rank_categories = count_wallets_by_rank(current_wallets_data)
       
        comparison_results = []

        previous_wallets_dict = {wallet["Wallet"]: wallet for wallet in previous_wallets_data}

        for current in current_wallets_data:
            wallet_address = current["Wallet"]
            if wallet_address in previous_wallets_dict:
                previous = previous_wallets_dict[wallet_address]
                
                points_change = current["Points"] - previous["Points"]
                rank_change = current["Rank"] - previous["Rank"]

                comparison_results.append({
                    "Wallet": wallet_address,
                    "Points Change": points_change,
                    "Rank Change": rank_change,
                    "Current Rank": current["Rank"],
                    "Increased Points": points_change > 0,
                    "Increased Rank": rank_change < 0,
                    "Points Difference": f"+{points_change:.3f}" if points_change > 0 else f"{points_change:.3f}"
                })

        sorted_by_rank = sorted(
            [wallet for wallet in current_wallets_data if wallet["Rank"] > 0], 
            key=lambda x: x["Rank"]
        )[:10]

        compare_log_filename = datetime.now().strftime("compare_result_%d-%m-%y-%Hx%M.csv")
        with open(compare_log_filename, "w") as f:
            for result in comparison_results:
                f.write(
                    f"Wallet: {result['Wallet']}, Points Change: {result['Points Change']}, "
                    f"Rank Change: {result['Rank Change']}, Current Rank: {result['Current Rank']}, "
                    f"Increased Points: {'Yes' if result['Increased Points'] else 'No'}, "
                    f"Increased Rank: {'Yes' if result['Increased Rank'] else 'No'}, "
                    f"Points Difference: {result['Points Difference']}\n"
                )
            
            f.write("\n--- Summary ---\n")
            f.write(f"Previous Total Points: {previous_total_points:.3f}, Wallets with Points: {previous_wallets_with_points}\n")
            f.write(f"Current Total Points: {current_total_points:.3f}, Wallets with Points: {current_wallets_with_points}\n")
            f.write(f"Difference in Total Points: {current_total_points - previous_total_points:.3f}\n")
            f.write(f"Difference in Wallets with Points: {current_wallets_with_points - previous_wallets_with_points}\n")
        
            f.write("\n--- Top 10 Wallets by Rank ---\n")
            for wallet in sorted_by_rank:
                f.write(f"Wallet: {wallet['Wallet']}, Rank: {wallet['Rank']}, Points: {wallet['Points']:.3f}\n")

            f.write("\n--- Wallets by Points Categories (Previous) ---\n")
            for category, count in previous_categories.items():
                f.write(f"{category}: {count}\n")
            
            f.write("\n--- Wallets by Points Categories (Current) ---\n")
            for category, count in current_categories.items():
                f.write(f"{category}: {count}\n")
        
            f.write("\n--- Wallets by Rank Categories (Previous) ---\n")
            for category, count in previous_rank_categories.items():
                f.write(f"{category}: {count}\n")
            
            f.write("\n--- Wallets by Rank Categories (Current) ---\n")
            for category, count in current_rank_categories.items():
                f.write(f"{category}: {count}\n")
        
            print(f"Compared stats and results with saved to {compare_log_filename}")

if __name__ == "__main__":
    main()
