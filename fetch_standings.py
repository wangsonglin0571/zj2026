#!/usr/bin/env python3
"""
抓取懂球帝中超积分榜，生成 data.json
"""
import json, re, time, requests
from bs4 import BeautifulSoup

URL = "https://www.dongqiudi.com/data/231"
OUT = "data.json"

# 扣分配置（赛季固定）
PENALTIES = {
    "天津津门虎": -10,
    "上海申花":   -10,
    "青岛海牛":    -7,
    "山东泰山":    -6,
    "河南":        -6,
    "上海海港":    -5,
    "北京国安":    -5,
    "武汉三镇":    -5,
    "浙江":        -5,
}

RIVALS = ["成都蓉城", "北京国安", "上海海港", "山东泰山", "上海申花"]

COLORS = {
    "成都蓉城": "#3b82f6",
    "北京国安": "#a855f7",
    "上海海港": "#06b6d4",
    "山东泰山": "#eab308",
    "上海申花": "#6b7280",
}

ALL_TEAMS = [
    "成都蓉城","重庆铜梁龙","大连英博","云南玉昆","辽宁铁人",
    "深圳新鹏城","青岛西海岸","山东泰山","浙江","上海申花",
    "上海海港","河南","北京国安","武汉三镇","青岛海牛","天津津门虎"
]

def fetch():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        "Referer": "https://www.dongqiudi.com/",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    r = requests.get(URL, headers=headers, timeout=20)
    r.raise_for_status()
    return r.text

def parse(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    teams = []
    i = 0
    while i < len(lines):
        name = lines[i]
        if name in ALL_TEAMS:
            # 找后续数字：场次 胜 平 负 进 失 净 积分
            nums = []
            for j in range(i + 1, min(i + 10, len(lines))):
                found = re.findall(r'-?\d+', lines[j])
                nums.extend(found)
                if len(nums) >= 8:
                    break
            if len(nums) >= 8:
                pts_raw = int(nums[7])          # 第8个数字是积分
                penalty = PENALTIES.get(name, 0)
                teams.append({
                    "name":    name,
                    "penalty": penalty,
                    "gamePts": pts_raw,
                    "actual":  pts_raw + penalty,
                })
        i += 1

    return teams

def main():
    print("Fetching standings from dongqiudi...")
    try:
        html = fetch()
    except Exception as e:
        print(f"Fetch failed: {e}")
        return

    teams = parse(html)
    print(f"Parsed {len(teams)} teams")

    if len(teams) < 10:
        print("Too few teams parsed, aborting to avoid bad data")
        return

    zj = next((t for t in teams if t["name"] == "浙江"), None)
    if not zj:
        print("浙江 not found, abort")
        return

    rivals_data = []
    for name in RIVALS:
        t = next((x for x in teams if x["name"] == name), None)
        if t:
            rivals_data.append({
                "name":    t["name"],
                "penalty": t["penalty"],
                "basePts": t["gamePts"],
                "actual":  t["actual"],
                "color":   COLORS.get(name, "#888"),
            })

    data = {
        "updated":   time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "zhejiang": {
            "gamePts": zj["gamePts"],
            "actual":  zj["actual"],
            "penalty": zj["penalty"],
        },
        "rivals":   rivals_data,
        "allTeams": sorted(teams, key=lambda x: -x["actual"]),
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✓ {OUT} updated")
    print(f"  浙江: 比赛积分{zj['gamePts']} 实际{zj['actual']:+d}")
    for r in rivals_data:
        print(f"  {r['name']}: {r['actual']:+d}")

if __name__ == "__main__":
    main()
