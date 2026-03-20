import os
import requests
import json
import netaddr

ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
POLICY_ID = os.getenv("CLOUDFLARE_POLICY_ID")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")

IPRANGE_URLS = {
    "goog": "https://www.gstatic.com/ipranges/goog.json",
    "cloud": "https://www.gstatic.com/ipranges/cloud.json",
}

def get_google_bot_ips():
    """Lấy và lọc dải IP của Google Bot"""
    try:
        goog_data = requests.get(IPRANGE_URLS["goog"]).json()
        cloud_data = requests.get(IPRANGE_URLS["cloud"]).json()

        goog_ips = netaddr.IPSet([e.get("ipv4Prefix") or e.get("ipv6Prefix")
                                 for e in goog_data["prefixes"]])
        cloud_ips = netaddr.IPSet([e.get("ipv4Prefix") or e.get("ipv6Prefix")
                                  for e in cloud_data["prefixes"]])

        # Phép toán: Google Services - Google Cloud Khách hàng
        return goog_ips - cloud_ips
    except Exception as e:
        print(f"Lỗi khi lấy dữ liệu IP: {e}")
        return None

def update_cloudflare_policy(bot_ips):
    """Gửi request PUT để cập nhật Policy"""
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/access/policies/{POLICY_ID}"

    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json"
    }

    # Xây dựng danh sách "include" theo đúng format bạn yêu cầu
    include_list = []
    for cidr in bot_ips.iter_cidrs():
        include_list.append({
            "ip": {
                "ip": str(cidr)
            }
        })

    payload = {
        "decision": "bypass",
        "include": include_list,
        "name": "google bot"
    }

    print(f"--- Đang gửi request cập nhật {len(include_list)} dải IP... ---")

    response = requests.put(url, headers=headers, json=payload)

    if response.status_code == 200:
        print("✅ Cập nhật thành công!")
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"❌ Thất bại! Mã lỗi: {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    ips = get_google_bot_ips()
    if ips:
        update_cloudflare_policy(ips)