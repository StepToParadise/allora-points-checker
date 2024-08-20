import requests
import json
import time
import random
import brotli
from datetime import datetime

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

def send_post_request(wallet, headers, url):
    if wallet.startswith("0x"):
        payload = {"allora_address": None, "evm_address": wallet}
    else:
        payload = {"allora_address": wallet, "evm_address": None}
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        if response.text:
            return response.json()
        else:
            print(f"Empty response received for wallet: {wallet}")
            return None
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
        return None
    except json.JSONDecodeError as json_err:
        print(f"JSON decode error: {json_err} for wallet: {wallet} with response: {response.text}")
        return None
    except Exception as err:
        print(f"Other error occurred: {err} for wallet: {wallet}")
        return None

def send_get_request(data_id, headers, url):
    try:
        response = requests.get(url.format(id=data_id), headers=headers)
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
        
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
        return None
    except json.JSONDecodeError as json_err:
        print(f"JSON decode error: {json_err} for ID: {data_id} with response: {response.content}")
        return None
    except Exception as err:
        print(f"Other error occurred: {err} for ID: {data_id}")
        return None

def log_result(wallet, data_id, points, rank, log_filename):
    with open(log_filename, 'a') as file:
        file.write(f"Wallet: {wallet} | ID: {data_id} | Points: {points} | Rank: {rank}\n")

def main():
    url_post = "https://api.upshot.xyz/v2/allora/users/connect"
    url_get = "https://api.upshot.xyz/v2/allora/points/{id}"

    headers_post = {
        "accept": "application/json, text/plain, */*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "content-length": "83",
        "content-type": "application/json",
        "dnt": "1",
        "origin": "https://app.allora.network",
        "priority": "u=1, i",
        "referer": "https://app.allora.network/",
        "sec-ch-ua": '"Not)A;Brand";v="99", "Google Chrome";v="127", "Chromium";v="127"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "macOS",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "cross-site",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        "x-api-key": "UP-0d9ed54694abdac60fd23b74"
    }

    headers_get = {
        "accept": "application/json, text/plain, */*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "dnt": "1",
        "if-none-match": 'W/"180-wWc9Nj5jKOz4m2gZtCQbgGkX8dg"',
        "origin": "https://app.allora.network",
        "priority": "u=1, i",
        "referer": "https://app.allora.network/",
        "sec-ch-ua": '"Not)A;Brand";v="99", "Google Chrome";v="127", "Chromium";v="127"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "macOS",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "cross-site",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        "x-api-key": "UP-0d9ed54694abdac60fd23b74"
    }

    wallets = read_wallets('wallets.txt')
    log_filename = datetime.now().strftime("result_%H%M%d%m%y.log")
    
    for wallet in wallets:
        post_response = send_post_request(wallet, headers_post, url_post)
        if post_response and post_response.get("status"):
            data_id = post_response.get("data", {}).get("id")
            if data_id:
                get_response = send_get_request(data_id, headers_get, url_get)
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
                        continue
        time.sleep(random.randint(1, 10))

if __name__ == "__main__":
    main()
