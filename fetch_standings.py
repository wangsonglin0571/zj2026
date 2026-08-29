#!/usr/bin/env python3
"""
抓取中超积分榜和赛程，生成 data.json

数据源：直播吧/球球炮数据 API (stats.qiumibao.com)
- 积分榜: endpoint with type=积分榜, league_id=353
- 赛程:   endpoint with type=赛程, league_id=353
"""
import argparse, json, re, time, requests
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

STANDINGS_URL = (
    "https://stats.qiumibao.com/shuju/public/index.php"
    "?_url=/data/index&year=2026&type=积分榜"
    "&tab=积分榜&league_id=353&league=中超"
)
SCHEDULE_URL = (
    "https://stats.qiumibao.com/shuju/public/index.php"
    "?_url=/data/index&year=2026&type=赛程"
    "&tab=赛程&league_id=353&league=中超"
)
OUT = "data.json"

ZHEJIANG_HOME = {
    "venue": "黄龙体育中心体育场",
    "location": "浙江杭州",
}

# 球球炮赛程 API 只给主客队和时间，不给球场；下一场如果是客场，
# 不能沿用上一场/旧 data.json 的黄龙信息。这里维护常用主场映射，
# 未覆盖时至少显示“<主队>主场”，避免错误显示为浙江主场。
HOME_VENUES = {
    "浙江": ZHEJIANG_HOME,
    "上海海港": {"venue": "上汽浦东足球场", "location": "上海浦东"},
    "上海申花": {"venue": "上海体育场", "location": "上海"},
    "山东泰山": {"venue": "济南奥体中心体育场", "location": "山东济南"},
    "北京国安": {"venue": "北京工人体育场", "location": "北京"},
    "成都蓉城": {"venue": "凤凰山体育公园专业足球场", "location": "四川成都"},
    "深圳新鹏城": {"venue": "深圳市体育中心体育场", "location": "广东深圳"},
    "天津津门虎": {"venue": "天津泰达足球场", "location": "天津"},
    "河南": {"venue": "郑州航海体育场", "location": "河南郑州"},
    "大连英博": {"venue": "大连梭鱼湾足球场", "location": "辽宁大连"},
    "青岛西海岸": {"venue": "青岛西海岸大学城体育场", "location": "山东青岛"},
    "青岛海牛": {"venue": "青岛青春足球场", "location": "山东青岛"},
    "武汉三镇": {"venue": "武汉体育中心体育场", "location": "湖北武汉"},
    "云南玉昆": {"venue": "玉溪高原体育运动中心体育场", "location": "云南玉溪"},
    "重庆铜梁龙": {"venue": "重庆铜梁龙体育场", "location": "重庆"},
    "辽宁铁人": {"venue": "沈阳奥体中心体育场", "location": "辽宁沈阳"},
}
BEIJING = timezone(timedelta(hours=8))

# 竞争对手（用于排名跟踪）
RIVALS = ["成都蓉城", "北京国安", "上海海港", "山东泰山", "上海申花"]
COLORS = {
    "成都蓉城": "#3b82f6",
    "北京国安": "#a855f7",
    "上海海港": "#06b6d4",
    "山东泰山": "#eab308",
    "上海申花": "#6b7280",
}


# ── 通用 HTTP ──────────────────────────────────────────

def fetch_json(url, timeout=20, retries=2):
    """GET JSON from URL, return decoded dict."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(1 + attempt)
    raise last_err


# ── 积分榜（替换懂球帝爬虫）──────────────────────────

def parse_standings(api_data: dict) -> list:
    """
    解析积分榜 API 返回值。
    返回 list[dict]，每支球队含：
      name, played, wins, draws, losses, gf, ga, gd,
      penalty, gamePts, actual
    """
    raw_list = api_data["data"][0]["list"]
    teams = []
    for row in raw_list:
        name = row["球队"]
        played = int(row["场次"])
        wins = int(row["胜"])
        draws = int(row["平"])
        losses = int(row["负"])
        gf_ga = row["进/失球"]
        gf, ga = (int(x) for x in gf_ga.split("/"))
        gd = int(row["净胜球"])
        actual = int(row["积分"])          # API 返回的是扣分后实际积分
        game_pts = wins * 3 + draws        # 比赛积分（扣分前）
        penalty = game_pts - actual        # 推算扣分

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
            "actual":  actual,
        })
    return teams


# ── 赛程（替换直播吧首页爬虫）──────────────────────────

def parse_schedule(api_data: dict, teams: list) -> dict:
    """
    解析赛程 API 返回值。
    返回 {
      "zhejiang_matches": [...],    # 浙江队所有比赛
      "next_match": {...},          # 下一场未开始的浙江队比赛
      "round_matches": [list],      # 完整赛程（每轮次数组）
    }
    """
    now = datetime.now(BEIJING).replace(tzinfo=None)

    zj_matches = []
    next_match = None

    for round_idx, group in enumerate(api_data["data"], start=1):
        for match in group.get("list", []):
            home = match["主队"]
            away = match["客队"]
            score = match.get("比分", "-")
            is_finish = match.get("is_finish", 0)

            # 格式化 kickoff 时间
            date_str = match.get("日期", "")
            time_str = match.get("时间", "")
            # API 返回的时间格式是 "03-08 15:30" 或 "05-02 19:35"
            if time_str:
                parts = time_str.split(" ")
                if len(parts) == 2:
                    ktime = parts[1]  # "19:35"
                else:
                    ktime = parts[0]
            else:
                ktime = ""
            kickoff_bjt = f"{date_str} {ktime}" if ktime else date_str

            match_data = {
                "round": round_idx,
                "date": date_str,
                "kickoffBjt": kickoff_bjt.strip(),
                "home": home,
                "away": away,
                "score": score,
                "finished": (is_finish == 1),
            }

            # 浙江队的比赛
            if home == "浙江" or away == "浙江":
                opponent = away if home == "浙江" else home
                match_data["opponent"] = opponent
                match_data["isHome"] = (home == "浙江")
                zj_matches.append(match_data)

                # 找下一场未开始的比赛。
                # 球球炮会把已延期但未定新日期的旧比赛保留为 is_finish=0，
                # 例如 2026-08-08 浙江 vs 武汉三镇显示“延期”。这类比赛不能
                # 挡住真正下一场已确定开球时间的比赛。
                if not is_finish and next_match is None:
                    is_postponed_without_time = "延期" in (time_str or "") or "延期" in (kickoff_bjt or "")
                    if opponent not in ("", "待更新") and not is_postponed_without_time:
                        nm = {
                            "opponent": opponent,
                            "kickoffBjt": kickoff_bjt.strip(),
                            "note": f"中超第{round_idx}轮",
                        }
                        nm["home"] = home
                        nm["away"] = away
                        nm["isHome"] = (home == "浙江")
                        venue_info = HOME_VENUES.get(home, {
                            "venue": f"{home}主场",
                            "location": home,
                        })
                        nm.update(venue_info)
                        next_match = nm

    # 所有对手的 played（从赛程统计）
    # 对于每支球队，统计已完赛的场次数
    all_team_names = {t["name"] for t in teams}
    team_played = {}
    for round_idx, group in enumerate(api_data["data"], start=1):
        for match in group.get("list", []):
            if match.get("is_finish") != 1:
                continue
            home = match["主队"]
            away = match["客队"]
            for t in (home, away):
                if t in all_team_names:
                    team_played[t] = team_played.get(t, 0) + 1

    return {
        "zhejiang_matches": zj_matches,
        "next_match": next_match or {
            "opponent": "待更新",
            "kickoffBjt": "",
            "venue": "",
            "location": "",
            "note": "中超",
        },
        "round_matches": api_data["data"],
        "team_played": team_played,
    }


# ── 数据组装 ──────────────────────────────────────────

def load_old_data():
    try:
        with open(OUT, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def collect_data():
    # 1) 抓取积分榜
    try:
        standings_json = fetch_json(STANDINGS_URL)
    except Exception as e:
        raise RuntimeError(f"积分榜 API 请求失败: {e}") from e

    teams = parse_standings(standings_json)
    if len(teams) < 10:
        raise RuntimeError(f"积分榜解析异常，仅拿到 {len(teams)} 支球队")

    # 2) 抓取赛程
    try:
        schedule_json = fetch_json(SCHEDULE_URL)
    except Exception as e:
        raise RuntimeError(f"赛程 API 请求失败: {e}") from e

    schedule_info = parse_schedule(schedule_json, teams)
    team_played = schedule_info["team_played"]

    # 3) 浙江队数据
    zj = next((t for t in teams if t["name"] == "浙江"), None)
    if not zj:
        raise RuntimeError("积分榜中未找到浙江")

    # 4) 对手数据（含 played 字段）
    rivals_data = []
    for name in RIVALS:
        t = next((x for x in teams if x["name"] == name), None)
        if t:
            rivals_data.append({
                "name":    t["name"],
                "played":  team_played.get(name, t["played"]),
                "penalty": t["penalty"],
                "basePts": t["gamePts"],
                "actual":  t["actual"],
                "color":   COLORS.get(name, "#888"),
            })

    # 5) 组装输出
    old_data = load_old_data()
    next_match = schedule_info["next_match"]
    # 兼容旧 data.json：只有当仍是同一场比赛时，才回填旧 venue/location。
    # 如果下一场已从主场变成客场，绝不能把上一场黄龙信息带过去。
    old_next = old_data.get("nextMatch", {})
    same_next_match = (
        old_next.get("opponent") == next_match.get("opponent")
        and old_next.get("kickoffBjt") == next_match.get("kickoffBjt")
        and old_next.get("isHome") == next_match.get("isHome")
    )
    if same_next_match:
        if not next_match.get("venue") and old_next.get("venue"):
            next_match["venue"] = old_next["venue"]
        if not next_match.get("location") and old_next.get("location"):
            next_match["location"] = old_next["location"]

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
        "matches":  schedule_info["zhejiang_matches"],   # 新增：浙江队完整赛程
    }


def write_data(data):
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def print_summary(data, prefix=""):
    zj = data["zhejiang"]
    next_match = data["nextMatch"]
    print(f"{prefix}浙江: 比赛积分{zj['gamePts']} 实际{zj['actual']:+d}")
    home = next_match.get("home", "浙江" if next_match.get("isHome", True) else next_match.get("opponent", "待定"))
    away = next_match.get("away", next_match.get("opponent", "待定") if next_match.get("isHome", True) else "浙江")
    print(f"{prefix}下一场: {next_match['kickoffBjt']} {home} vs {away}")
    for r in data["rivals"]:
        print(f"{prefix}{r['name']}: 已赛{r['played']}轮 {r['actual']:+d}分")
    print(f"{prefix}赛程: 共 {len(data.get('matches', []))} 场")
    finished = sum(1 for m in data.get("matches", []) if m["finished"])
    print(f"{prefix}      已完赛 {finished} 场 / 待进行 {len(data.get('matches', [])) - finished} 场")


def check_sources():
    print("Checking standings source (stats.qiumibao.com)...")
    data = collect_data()
    print(f"OK: 解析到 {len(data['allTeams'])} 支球队")
    print_summary(data, prefix="  ")
    next_match = data["nextMatch"]
    if next_match.get("kickoffBjt"):
        print("OK: 下一场赛程源可用")
    else:
        print("WARN: 未解析到下一场比赛")


def run_update():
    print("Fetching standings from stats.qiumibao.com...")
    print("Fetching schedule from stats.qiumibao.com...")
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
