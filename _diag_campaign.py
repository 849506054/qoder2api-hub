# -*- coding: utf-8 -*-
"""_diag_campaign.py —— 活动资格与新人权益自检（为什么我没有签到/新人活动）

对账号池里的每个账号输出一份"权益体检"：
  1. 机器身份来源（官方原生桥 runtime-info.exe / 派生回退）与 VM 检测结果
  2. 套餐与额度（plan / userType / 基础额度 / 资源包）
  3. 活动平台列表（每条活动的状态、奖励、成就要求、不可用原因）
  4. 成就列表（哪些任务已完成）
  5. 结论与常见原因（对照官方规则）

只读：不领取任何活动。用法：
    python _diag_campaign.py            # 体检全部账号
    python _diag_campaign.py --uid XX   # 只看某个账号（uid 前缀匹配）
退出码：0=成功输出；1=无可用账号。
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("ACCOUNTS_DIR", os.path.join(HERE, "accounts"))
os.environ.setdefault("USAGE_DIR", os.path.join(HERE, "usage"))
os.chdir(HERE)

import qoder_accounts as A   # noqa: E402
import qoder_proxy as P      # noqa: E402

RULES = """
官方规则速查（详见 README「活动与新人权益规则」）：
  · 每日 100 Credits：每账号每轮限领一次（按账号，不是按设备）；每日 10:00
    （UTC+8）刷新，错过不补；30 天有效；仅桌面端可领；新老个人用户均可。
  · 新人 300（14 天 Pro 试用的一部分）：首次登录最新版桌面客户端时发放；
    虚拟机不参与；每用户限一次，额外注册的试用账号会被冻结。
  · 新人任务活动（如 CN「奶茶免单卡」act-20260928-620）：要求完成指定成就
    （sites_first_use = 桌面端「站点」发布 AI 站点），完成后才可领取。
常见"没有活动/没有 300"的原因：
  ① 账号不在活动定向内（服务端按账号/风控决定，reward 404 即未登记）；
  ② 虚拟机环境（runtime-info 会回报 isVm，官方明说 VM 不参与新人试用）；
  ③ 同用户/同设备已用过试用（额外注册的账号被冻结）；
  ④ 只注册了网页账号、未登录过最新版桌面客户端（300 在首次登录时发放）；
  ⑤ 成就未完成（任务类活动显示 ACHIEVEMENT_NOT_COMPLETED）。
"""


def identity_report(realm, account_id):
    exe = A.runtime_info_exe(realm)
    if not exe:
        return "机器身份=派生回退（未找到官方 runtime-info.exe；设备定向活动可能被过滤）"
    ident = A.native_machine_identity(realm, account_id)
    if not ident:
        return "机器身份=派生回退（runtime-info.exe 调用失败）"
    return "机器身份=官方原生桥 runtime-info（真实身份，来源可信）"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--uid", default="", help="只体检 uid 前缀匹配的账号")
    args = ap.parse_args()
    pool = A.AccountPool(os.environ["ACCOUNTS_DIR"], log=lambda m: None)
    pool.load()
    accs = [a for a in pool.accounts
            if not args.uid or a.uid.startswith(args.uid)]
    if not accs:
        print("没有可用账号（accounts 目录为空或未匹配）")
        return 1
    print(RULES)
    for acc in accs:
        print("=" * 78)
        print("账号 %s realm=%s added=%s plan=%s"
              % (acc.uid[:8], acc.realm, acc.added_at, acc.plan or "-"))
        # 1) 机器身份
        print("  [机器身份]", identity_report(acc.realm, acc.uid),
              "| 来源=", (A.native_machine_identity(acc.realm, acc.uid) or {})
              .get("source", "derived"))
        # 2) 套餐与额度
        if acc.fetch_credits().get("ok"):
            pk = acc.credits.get("packages") or [{}, {}]
            print("  [套餐额度] remain=%s (基础 %s/%s + 资源包 %s/%s) exceeded=%s"
                  % (acc.credits.get("remain"), pk[0].get("remain"),
                     pk[0].get("size"), pk[1].get("remain"),
                     pk[1].get("size"), acc.credits.get("exceeded")))
        # 3) 活动平台
        st = acc.campaigns()
        print("  [活动平台] ok=%s show=%s claimable=%s identity=%s 条数=%d"
              % (st.get("ok"), st.get("show_campaign"), st.get("claimable"),
                 st.get("identity"), len(st.get("campaigns") or [])))
        for c in st.get("campaigns") or []:
            print("      - %-18s %-28s %-14s +%s 成就=%s(%s)"
                  % (c["campaign_key"], c["claim_status"], c["action_type"],
                     c["benefit"]["amount"],
                     c.get("required_achievement_key") or "-",
                     "已完成" if c.get("achievement_completed") else "未完成"))
        if st.get("ok") and not st.get("campaigns"):
            print("      （列表为空：请求头/机器身份问题，或该账号不在任何活动定向内）")
        # 4) 成就
        try:
            ach = A.http_json(A.get_realm_config(acc.realm)["openapi"]
                              + "/sash/api/v1/me/achievements", method="GET",
                              headers=acc.desktop_headers(), timeout=20, retries=1)
            items = ach.get("achievements") or []
            print("  [成就] %s" % (json.dumps(items, ensure_ascii=False)[:200]
                                   if items else "（无）"))
        except Exception as exc:
            print("  [成就] 查询失败 %s" % str(exc)[:100])
        # 5) 判定
        daily = [c for c in st.get("campaigns") or []
                 if c["action_type"] == "CLAIM_BENEFIT"]
        if any(c["claim_status"] == "CLAIMABLE" for c in daily):
            print("  [结论] 本账号在每日领取活动定向内，可在窗口内领取（网关会自动领取）。")
        elif any(c["claim_status"] == "CLAIMED" for c in daily):
            print("  [结论] 本轮每日奖励已领取，等下一轮（每日 10:00 UTC+8 刷新）。")
        elif daily:
            print("  [结论] 有活动但未达成条件（成就未完成），需在官方桌面端完成任务。")
        else:
            print("  [结论] 服务端未把本账号纳入当前活动定向（可能原因见上方常见原因①-④）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
