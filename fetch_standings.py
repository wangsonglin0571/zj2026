#!/usr/bin/env python3
"""
抓取懂球帝中超积分榜，并从直播吧赛事表提取浙江下一场比赛，生成 data.json
"""
import argparse, json, re, time, requests
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

URL = "https://www.dongqiudi.com/data/231"
LIVEBAR_URL = "https://www.zhibo8.com/"
OUT = "data.json"
ZHEJIANG_HOME = {
    "venue": "黄龙体育中心体育场",
    "location": "浙江杭州",
}
BEIJING = timezone(timedelta(hours=8))

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

def make_headers(referer):
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/135.0.0.0 Safari/537.36"
        ),
        "Referer": referer,
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


def fetch_url(url, referer, timeout=20, retries=2):
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=make_headers(referer), timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(1 + attempt)
    raise last_err


def fetch():
    return fetch_url(URL, "https://www.dongqiudi.com/")


def fetch_livebar():
    return fetch_url(LIVEBAR_URL, "https://www.zhibo8.com/")

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
                played = int(nums[0])
                wins = int(nums[1])
                draws = int(nums[2])
                losses = int(nums[3])
                gf = int(nums[4])
                ga = int(nums[5])
                gd = int(nums[6])
                actual_pts = int(nums[7])       # 懂球帝榜单已是扣分后的当前积分
                game_pts = wins * 3 + draws     # 比赛积分按胜平负回算，避免重复扣分
                penalty = PENALTIES.get(name, 0)
                teams.append({
                    "name":    name,
                    "played":  played,
                    "wins":    wins,
                    "draws":   draws,
                    "losses":  losses,
                    "gf":      gf,
                    "ga":      ga,
                    "gd":      gd,
                    "penalty": penalty,
                    "gamePts": game_pts,
                    "actual":  actual_pts,
                })
        i += 1

    return teams


def parse_livebar_next_match(html, previous=None):
    soup = BeautifulSoup(html, "html.parser")
    now = datetime.now(BEIJING).replace(tzinfo=None)

    for item in soup.select('li[data-type="football"][data-time]'):
        label = item.get("label", "")
        if "中超" not in label or "浙江" not in label:
            continue

        time_str = item.get("data-time", "").strip()
        try:
            kickoff = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if kickoff < now:
            continue

        parts = [p.strip() for p in label.split(",") if p.strip()]
        filtered = [
            p for p in parts
            if p not in {"中超", "足球", "中国足球"} and not p.startswith("中超第")
        ]
        if len(filtered) < 2:
            continue

        home, away = filtered[0], filtered[1]
        opponent = away if home == "浙江" else home
        note = next((p for p in parts if p.startswith("中超第")), "中超")

        match = {
            "opponent": opponent,
            "kickoffBjt": kickoff.strftime("%Y-%m-%d %H:%M"),
            "note": note,
        }

        if home == "浙江":
            match.update(ZHEJIANG_HOME)
        elif (
            previous
            and previous.get("opponent") == opponent
            and previous.get("kickoffBjt") == kickoff.strftime("%Y-%m-%d %H:%M")
        ):
            match["venue"] = previous.get("venue", "")
            match["location"] = previous.get("location", "")
        else:
            match["venue"] = ""
            match["location"] = ""

        return match

    if previous:
        kickoff = previous.get("kickoffBjt", "")
        try:
            prev_dt = datetime.strptime(kickoff, "%Y-%m-%d %H:%M")
        except ValueError:
            prev_dt = None
        if prev_dt and prev_dt >= now:
            return previous

    return {
        "opponent": "待更新",
        "kickoffBjt": "",
        "venue": "",
        "location": "",
        "note": "中超",
    }

def load_old_data():
    try:
        with open(OUT, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def collect_data():
    try:
        html = fetch()
    except Exception as e:
        raise RuntimeError(f"懂球帝抓取失败: {e}") from e
    try:
        livebar_html = fetch_livebar()
    except Exception as e:
        print(f"Livebar fetch failed: {e}")
        livebar_html = ""

    teams = parse(html)
    if len(teams) < 10:
        raise RuntimeError(f"积分榜解析异常，仅拿到 {len(teams)} 支球队")

    zj = next((t for t in teams if t["name"] == "浙江"), None)
    if not zj:
        raise RuntimeError("积分榜中未找到浙江")

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

    old_data = load_old_data()
    next_match = parse_livebar_next_match(livebar_html, old_data.get("nextMatch"))

    return {
        "updated":   time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "nextMatch": next_match,
        "zhejiang": {
            "played":  zj["played"],
            "wins":    zj["wins"],
            "draws":   zj["draws"],
            "losses":  zj["losses"],
            "gf":      zj["gf"],
            "ga":      zj["ga"],
            "gd":      zj["gd"],
            "gamePts": zj["gamePts"],
            "actual":  zj["actual"],
            "penalty": zj["penalty"],
        },
        "rivals":   rivals_data,
        "allTeams": sorted(teams, key=lambda x: -x["actual"]),
    }


def write_data(data):
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def print_summary(data, prefix=""):
    zj = data["zhejiang"]
    next_match = data["nextMatch"]
    print(f"{prefix}浙江: 比赛积分{zj['gamePts']} 实际{zj['actual']:+d}")
    print(f"{prefix}下一场: {next_match['kickoffBjt']} 浙江 vs {next_match['opponent']}")
    for r in data["rivals"]:
        print(f"{prefix}{r['name']}: {r['actual']:+d}")


def check_sources():
    print("Checking standings source (dongqiudi)...")
    data = collect_data()
    print(f"OK: 解析到 {len(data['allTeams'])} 支球队")
    print_summary(data, prefix="  ")
    next_match = data["nextMatch"]
    if next_match.get("kickoffBjt"):
        print("OK: 下一场赛程源可用")
    else:
        print("WARN: 未解析到下一场比赛")


def run_update():
    print("Fetching standings from dongqiudi...")
    print("Fetching next match from zhibo8...")
    data = collect_data()
    write_data(data)
    print(f"\n✓ {OUT} updated")
    print_summary(data, prefix="  ")


def parse_args():
    parser = argparse.ArgumentParser(description="更新浙江争冠页数据")
    parser.add_argument(
        "--check-sources",
        action="store_true",
        help="仅检查数据源和解析结果，不写入 data.json",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.check_sources:
        check_sources()
    else:
        run_update()

if __name__ == "__main__":
    main()
