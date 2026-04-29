import sys
import os
import time
import requests

try:
    import dotenv
    dotenv.load_dotenv()
except ImportError:
    print("Note: Not using .env file.")

API_TOKEN = os.getenv('CLOUDFLARE_API_TOKEN')
HEADERS = {
    'Authorization': f'Bearer {API_TOKEN}',
    'Content-Type': 'application/json',
}

DNS_CACHE = {}
CACHE_TTL = 300 # seconds

def get_list_dns_info(zone_id: str, name: str, type_filter: list) -> list:
    current_time = time.time()

    # Kiểm tra cache hợp lệ theo zone_id (vì API trả về toàn bộ zone)
    if zone_id in DNS_CACHE and (current_time - DNS_CACHE[zone_id]['timestamp']) < CACHE_TTL:
        dns_records = DNS_CACHE[zone_id]['data']
    else:
        url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            dns_records = response.json().get('result', [])

            # Cập nhật raw data vào cache kèm timestamp
            DNS_CACHE[zone_id] = {
                'timestamp': current_time,
                'data': dns_records
            }
        except Exception as e:
            print(f"Error fetching DNS info: {e}")
            return None

    # Thực hiện lọc data (từ cache hoặc mới tải về) theo đúng tham số yêu cầu
    dns_records_found = []
    for dns_record in dns_records:
        if dns_record['name'] == name and dns_record['type'] in type_filter:
            dns_records_found.append(dns_record)

    return dns_records_found

def update_dns_record(zone_id, dns_record_name, ip):
    list_dns_info = get_list_dns_info(zone_id, dns_record_name, ['A'])

    if list_dns_info is None:
        print(f"Failed to retrieve A record for {dns_record_name}")
        return
    if len(list_dns_info) == 0:
        print(f"A record for {dns_record_name} not found")
        return

    record = list_dns_info[0]

    if record['content'] == ip:
        print(f"IPv4 for {dns_record_name} is already up-to-date ({ip})")
        return

    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record['id']}"
    data = {
        'type': 'A',
        'name': dns_record_name,
        'content': ip,
        'proxied': True,
    }

    try:
        requests.patch(url, headers=HEADERS, json=data, timeout=30)
        print(f"Successfully updated IPv4 to {ip}")
    except Exception as e:
        print(f"Error updating IPv4 record: {e}")

def update_dns6_record(zone_id, dns_record_name, ipv6):
    list_dns_info = get_list_dns_info(zone_id, dns_record_name, ['AAAA'])

    if list_dns_info is None:
        print(f"Failed to retrieve AAAA record for {dns_record_name}")
        return
    if len(list_dns_info) == 0:
        print(f"AAAA record for {dns_record_name} not found")
        return

    record = list_dns_info[0]

    if record['content'] == ipv6:
        print(f"IPv6 for {dns_record_name} is already up-to-date ({ipv6})")
        return

    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record['id']}"
    data = {
        'type': 'AAAA',
        'name': dns_record_name,
        'content': ipv6,
        'proxied': True,
    }

    try:
        requests.patch(url, headers=HEADERS, json=data, timeout=30)
        print(f"Successfully updated IPv6 to {ipv6}")
    except Exception as e:
        print(f"Error updating IPv6 record: {e}")

def get_ip():
    try:
        return requests.get('https://api.ipify.org', timeout=30).text.strip()
    except Exception as e:
        print(f"Failed to get IPv4: {e}")
        return None

def get_ipv6():
    try:
        return requests.get('https://api6.ipify.org', timeout=30).text.strip()
    except requests.exceptions.ConnectionError:
        print("IPv6 not available.")
        return None
    except Exception as e:
        print(f"Failed to get IPv6: {e}")
        return None


if __name__ == '__main__':
    ZONE_ID = os.getenv('ZONE_ID')
    DNS_NAME = os.getenv('DNS_NAME')

    if not ZONE_ID or not DNS_NAME or not API_TOKEN:
        print("Error: ZONE_ID, DNS_NAME, and CLOUDFLARE_API_TOKEN must be set in environment/dotenv.")
        sys.exit(1)

    print(f"Checking IPs for {DNS_NAME}...")

    # Xử lý IPv4
    current_ip = get_ip()
    if current_ip:
        print(f"Detected IPv4: {current_ip}")
        update_dns_record(ZONE_ID, DNS_NAME, current_ip)
    else:
        print("Could not retrieve current IPv4. Skipping A record update.")

    # Xử lý IPv6
    current_ipv6 = get_ipv6()
    if current_ipv6:
        print(f"Detected IPv6: {current_ipv6}")
        update_dns6_record(ZONE_ID, DNS_NAME, current_ipv6)
    else:
        print("Could not retrieve current IPv6. Skipping AAAA record update.")