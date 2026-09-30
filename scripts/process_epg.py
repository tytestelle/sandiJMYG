#!/usr/bin/env python3
import requests
import xml.etree.ElementTree as ET
import os
import gzip
from urllib.parse import quote, unquote
import re
import hashlib
from collections import defaultdict
import ssl
import json
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

# ===================== 抓取 Kbro 节目数据 =====================
def fetch_kbro_programs(days=7):
    print("📡 开始抓取 Kbro 频道 906 节目...")
    ssl._create_default_https_context = ssl._create_unverified_context
    base_url = "https://epg.kbro.com.tw:2543/epg/epg_program.php"
    params = {"appid": "KBRO"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.kbro.com.tw/",
        "Origin": "https://www.kbro.com.tw"
    }
    programs = []
    start_date = datetime.now().date()
    date_list = [(start_date + timedelta(days=i)).strftime("%Y%m%d") for i in range(days)]
    for date_str in date_list:
        params["date"] = date_str
        try:
            resp = requests.get(base_url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"   ⚠️ 抓取 {date_str} 失败: {e}")
            continue
        if not data or "PROG" not in data:
            continue
        for item in data["PROG"]:
            if item.get("channelid") != "906":
                continue
            prog_name = item.get("programname", "")
            start_str = item.get("starttime", "")
            end_str = item.get("endtime", "")
            desc_str = item.get("programdescr", "")
            if not start_str or not end_str:
                continue
            prog_date = start_str[:8] if len(start_str) >= 8 else ""
            programs.append({
                "title": prog_name,
                "start": start_str + " +0800",
                "stop": end_str + " +0800",
                "desc": desc_str,
                "date": prog_date
            })
    print(f"   ✅ 共抓取 {len(programs)} 个节目")
    return programs

# ===================== 生成格式化节目字符串 =====================
def format_programs(programs):
    lines = []
    for p in programs:
        title_esc = escape(p["title"])
        desc_esc = escape(p["desc"]) if p["desc"] else ""
        lines.append(f'  <programme channel="456841" start="{p["start"]}" stop="{p["stop"]}">')
        lines.append(f'    <title lang="zh">{title_esc}</title>')
        if desc_esc:
            lines.append(f'    <desc>{desc_esc}</desc>')
        lines.append(f'    <date>{p["date"]}</date>')
        lines.append('    <audio>')
        lines.append('      <stereo>stereo</stereo>')
        lines.append('    </audio>')
        lines.append('  </programme>')
    return '\n'.join(lines)

# ===================== 原有功能函数 =====================
def safe_download(url):
    try:
        print(f"📥 下载: {url}")
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        r.encoding = 'utf-8'
        return r.text
    except Exception as e:
        print(f"❌ 下载失败: {e}")
        return None

def fix_icon_url(root):
    for ch in root.findall('channel'):
        icon = ch.find('icon')
        if icon is not None and 'src' in icon.attrib:
            raw = icon.attrib['src']
            decoded = unquote(raw)
            if decoded.startswith('//'):
                decoded = 'https:' + decoded
            icon.attrib['src'] = decoded

def fix_display_name(root):
    for ch in root.findall('channel'):
        for name in ch.findall('display-name'):
            if name.text:
                name.text = name.text.strip()

def normalize_channel_name(name):
    if not name:
        return name
    name = re.sub(r'[（(].*?[）)]', '', name)
    name = re.sub(r'[\[【].*?[\]】]', '', name)
    name = re.sub(r'CCTV[- ]?(\d+)[ ]?(综合|财经|综艺|体育|电影|电视剧|纪录|科教|戏曲|社会与法|新闻|少儿|音乐|奥林匹克|农业农村|高清)?', r'CCTV-\1', name, flags=re.IGNORECASE)
    name = re.sub(r'CCTV(\d+)', r'CCTV-\1', name, flags=re.IGNORECASE)
    name = re.sub(r'[\s\-_]*(高清|HD|标清|高标清|付费|测试)[\s\-_]*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[\s\-_]+$', '', name)
    return name.strip()

def simple_merge(contents):
    print("🔄 简单合并所有EPG数据（不去重）...")
    merged_root = ET.Element('tv')
    merged_root.set('source-info-name', 'JMYG Merged EPG (raw)')
    merged_root.set('generator-info-name', 'JMYG Merger')
    total_progs = 0
    total_channels = 0
    for src_name, content in contents:
        try:
            root = ET.fromstring(content)
            fix_icon_url(root)
            fix_display_name(root)
            for ch in root.findall('channel'):
                merged_root.append(ch)
                total_channels += 1
            for prog in root.findall('programme'):
                merged_root.append(prog)
                total_progs += 1
            print(f"✅ 已合并 {src_name} (频道数: {len(root.findall('channel'))}, 节目数: {len(root.findall('programme'))})")
        except Exception as e:
            print(f"❌ 处理 {src_name} 出错: {e}")
    print(f"📊 简单合并后总频道数: {total_channels}, 总节目数: {total_progs}")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(merged_root, encoding='utf-8').decode()

def clean_unused_channels(xml_content):
    print("🧹 开始清理无节目频道...")
    root = ET.fromstring(xml_content)
    refs = set()
    for prog in root.findall('programme'):
        ch = prog.get('channel')
        if ch:
            refs.add(ch)
    to_remove = []
    for ch in root.findall('channel'):
        cid = ch.get('id')
        if cid and cid not in refs:
            to_remove.append(ch)
    for ch in to_remove:
        root.remove(ch)
    print(f"🧹 删除了 {len(to_remove)} 个无节目频道，剩余频道数: {len(root.findall('channel'))}")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='utf-8').decode()

def deduplicate_epg(xml_content):
    print("🔄 开始高级去重...")
    root = ET.fromstring(xml_content)
    new_root = ET.Element('tv')
    new_root.set('source-info-name', 'JMYG Deduped EPG')
    new_root.set('generator-info-name', 'JMYG Deduper')

    norm_to_channel = {}
    id_to_preferred = {}
    for ch in root.findall('channel'):
        cid = ch.get('id')
        if not cid:
            continue
        name_elem = ch.find('display-name')
        raw_name = name_elem.text.strip() if name_elem is not None and name_elem.text else cid
        norm_name = normalize_channel_name(raw_name)
        if norm_name not in norm_to_channel:
            norm_to_channel[norm_name] = ch
            id_to_preferred[cid] = cid
        else:
            preferred_ch = norm_to_channel[norm_name]
            id_to_preferred[cid] = preferred_ch.get('id')

    for ch in norm_to_channel.values():
        new_root.append(ch)
    print(f"📊 频道去重后: {len(norm_to_channel)} (原 {len(root.findall('channel'))})")

    prog_groups = defaultdict(list)
    for prog in root.findall('programme'):
        orig_id = prog.get('channel')
        if not orig_id:
            continue
        preferred_id = id_to_preferred.get(orig_id, orig_id)
        start = prog.get('start', '')
        if not start:
            prog.set('channel', preferred_id)
            new_root.append(prog)
            continue
        start_minute = start[:12] if len(start) >= 12 else start
        key = (preferred_id, start_minute)
        prog_groups[key].append(prog)

    kept_count = 0
    for key, progs in prog_groups.items():
        if len(progs) == 1:
            best = progs[0]
        else:
            def score(p):
                s = 0
                if p.find('desc') is not None:
                    s += 10
                if p.find('sub-title') is not None:
                    s += 5
                title = p.find('title')
                if title is not None and title.text:
                    s += len(title.text)
                return s
            best = max(progs, key=score)
        best.set('channel', key[0])
        new_root.append(best)
        kept_count += 1

    print(f"📊 节目去重后: {kept_count} (原 {len(root.findall('programme'))})")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(new_root, encoding='utf-8').decode()

def simple_timezone_fix(xml_content):
    if xml_content:
        return xml_content.replace('+0000', '+0800').replace('UTC', '+0800')
    return xml_content

def save_data(content, filename):
    os.makedirs('epg_data', exist_ok=True)
    filepath = f'epg_data/{filename}'
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            existing = f.read()
        if existing == content:
            print(f"⏭️ 内容无变化，跳过保存: {filename}")
            return
    content_bytes = content.encode('utf-8')
    md5_hash = hashlib.md5(content_bytes).hexdigest()
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    with gzip.open(f'epg_data/{filename}.gz', 'wt', encoding='utf-8') as f:
        f.write(content)
    hash_filename = f"{filename}.hash"
    with open(f'epg_data/{hash_filename}', 'w', encoding='utf-8') as f:
        f.write(md5_hash)
    print(f"💾 已保存: {filename} (大小: {len(content_bytes)/1024/1024:.2f} MB, MD5: {md5_hash})")

# ===================== 加载 epg_data/epg_data.json 别名映射 =====================
def load_epgid_alias_map():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    json_path = os.path.join(repo_root, 'epg_data', 'epg_data.json')

    if not os.path.exists(json_path):
        print(f"⚠️ 未找到 epg_data.json: {json_path}")
        return {}

    print(f"📂 使用 epg_data.json: {json_path}")

    try:
        with open(json_path, 'r', encoding='utf-8-sig') as f:
            raw_content = f.read()
    except Exception as e:
        print(f"❌ 读取 epg_data.json 失败: {e}")
        return {}

    try:
        data = json.loads(raw_content)
    except Exception as e:
        print(f"❌ 解析 epg_data.json 失败: {e}")
        return {}

    alias_map = {}
    for item in data.get('epgs', []):
        epgid = (item.get('epgid') or '').strip()
        if not epgid:
            continue

        names = item.get('name') or ''
        for alias in names.split(','):
            alias = alias.strip()
            if not alias:
                continue

            old = alias_map.get(alias)
            if old is not None and old != epgid:
                print(f"⚠️ 别名冲突: {alias!r} -> {old!r} / {epgid!r}，保留 {old!r}")
                continue
            alias_map[alias] = epgid

    print(f"📋 已加载 epg_data.json 精确别名: {len(alias_map)} 条")
    return alias_map

# ===================== 央视归一化辅助 =====================
CCTV_NUM_RE = re.compile(r'CCTV[\s\-_]*(\d+\+?)', re.IGNORECASE)


def extract_cctv_num(s):
    if not s:
        return None
    m = CCTV_NUM_RE.search(s)
    if not m:
        return None
    return m.group(1).upper()


def pick_shortest_epgid(candidates):
    if not candidates:
        return None
    return min(candidates, key=len)


# ===================== 阶段 2: 在 CN XML 里归一化央视 =====================
def normalize_cctv_in_cn(xml_content, alias_map, only_cctv=True):
    """
    在原始 CN XML 内部做央视归一化：
      1) 遍历所有 <channel>，从 <display-name> 提取 CCTV 频道号；
      2) 按频道号分组；
      3) 每组按 (覆盖天数, 节目条数) 打分，保留数据最全的那个 channel；
      4) 保留 channel 的 id 改成 epg_data.json 中同频道号的 epgid，
         display-name 也改成 epgid 并移到第一位；
      5) 同组其它 channel 的 programme channel 属性一并改成 epgid
         （数据全部合并到 epgid 名下），然后移除那些空壳 channel；
      6) 时间重叠留给后面的 deduplicate_epg 去重。

    返回: (新 XML 字符串, 改动计数 dict)
    """
    if not xml_content or not alias_map:
        return xml_content, {"renamed_ch": 0, "renamed_prog": 0, "removed_ch": 0, "groups": 0}

    print("🔧 阶段 2: 在 CN EPG 中归一化央视频道...")

    try:
        root = ET.fromstring(xml_content)
    except Exception as e:
        print(f"❌ 解析 CN EPG 失败: {e}")
        return xml_content, {"renamed_ch": 0, "renamed_prog": 0, "removed_ch": 0, "groups": 0}

    # ---- 1. 构建 CCTV 频道号 -> epgid 映射 ----
    num_to_epgids = defaultdict(list)
    for alias, epgid in alias_map.items():
        if only_cctv and not epgid.upper().startswith('CCTV'):
            continue
        num = extract_cctv_num(epgid)
        if not num:
            continue
        if epgid not in num_to_epgids[num]:
            num_to_epgids[num].append(epgid)

    num_to_epgid = {}
    for num, epgids in num_to_epgids.items():
        num_to_epgid[num] = pick_shortest_epgid(epgids)

    print(f"   📋 CCTV 频道号 -> epgid: {len(num_to_epgid)} 条")
    for num in sorted(num_to_epgid.keys(), key=lambda x: (len(x), x)):
        print(f"      CCTV-{num} -> {num_to_epgid[num]!r}")

    # ---- 2. 统计每个 channel 的节目数据 ----
    prog_days_by_ch = defaultdict(set)
    prog_count_by_ch = defaultdict(int)
    for prog in root.findall('programme'):
        cid = prog.get('channel')
        start = prog.get('start', '')
        if not cid:
            continue
        prog_count_by_ch[cid] += 1
        if len(start) >= 8:
            prog_days_by_ch[cid].add(start[:8])

    def channel_score(cid):
        return (len(prog_days_by_ch.get(cid, ())), prog_count_by_ch.get(cid, 0))

    # ---- 3. 按 CCTV 频道号分组 channel ----
    num_to_channels = defaultdict(list)
    for ch in root.findall('channel'):
        cid = ch.get('id')
        if not cid:
            continue
        found_num = None
        for dn in ch.findall('display-name'):
            text = (dn.text or '').strip()
            num = extract_cctv_num(text)
            if num:
                found_num = num
                break
        if not found_num:
            continue
        if found_num not in num_to_epgid:
            continue
        num_to_channels[found_num].append(ch)

    # ---- 4. 每组选出主频道 ----
    id_rename_map = {}
    channels_to_remove = []
    main_channel_and_epgid = []

    for num, channels in num_to_channels.items():
        epgid = num_to_epgid.get(num)
        if not epgid:
            continue

        print(f"   📺 CCTV-{num} 候选（目标 epgid={epgid!r}）:")
        for ch in channels:
            cid = ch.get('id')
            dn_text = ''
            for dn in ch.findall('display-name'):
                t = (dn.text or '').strip()
                if extract_cctv_num(t):
                    dn_text = t
                    break
            days, cnt = channel_score(cid)
            print(f"      id={cid!r} 名称={dn_text!r} 天数={days} 节目数={cnt}")

        channels_sorted = sorted(channels, key=lambda ch: channel_score(ch.get('id')), reverse=True)
        best_ch = channels_sorted[0]
        best_id = best_ch.get('id')
        best_days, best_cnt = channel_score(best_id)

        print(f"   🎯 CCTV-{num}: 保留 id={best_id!r}（天数={best_days} 节目数={best_cnt}）-> epgid={epgid!r}")

        for ch in channels:
            old_id = ch.get('id')
            if old_id != epgid:
                id_rename_map[old_id] = epgid

        for ch in channels:
            if ch is not best_ch:
                channels_to_remove.append(ch)

        main_channel_and_epgid.append((best_ch, epgid, num))

    # ---- 5. 应用 id 重命名到 channel 和 programme ----
    renamed_ch = 0
    renamed_prog = 0
    if id_rename_map:
        for ch in root.findall('channel'):
            cid = ch.get('id')
            if cid in id_rename_map:
                ch.set('id', id_rename_map[cid])
                renamed_ch += 1
        for prog in root.findall('programme'):
            cid = prog.get('channel')
            if cid in id_rename_map:
                prog.set('channel', id_rename_map[cid])
                renamed_prog += 1
        print(f"   ✅ 已重命名 {renamed_ch} 个 <channel>，更新 {renamed_prog} 条 <programme> 引用")

    # ---- 6. 移除重复的空壳 channel ----
    removed = 0
    for ch in channels_to_remove:
        if ch in list(root):
            root.remove(ch)
            removed += 1
    if removed:
        print(f"   🧹 移除了 {removed} 个重复频道")

    # ---- 7. 主频道 display-name 改成 epgid 并移到第一位 ----
    for best_ch, epgid, num in main_channel_and_epgid:
        if best_ch not in list(root):
            continue
        display_names = best_ch.findall('display-name')
        if not display_names:
            continue

        match_idx = -1
        for i, dn in enumerate(display_names):
            text = (dn.text or '').strip()
            if extract_cctv_num(text):
                match_idx = i
                break
        if match_idx < 0:
            match_idx = 0

        display_names[match_idx].text = epgid

        if match_idx != 0:
            infos = [(dn.tag, dict(dn.attrib), dn.text) for dn in display_names]
            for dn in display_names:
                best_ch.remove(dn)
            new_order = [match_idx] + [i for i in range(len(infos)) if i != match_idx]
            for pos, i in enumerate(new_order):
                tag, attrib, text = infos[i]
                new_dn = ET.Element(tag, attrib)
                new_dn.text = text
                best_ch.insert(pos, new_dn)

    stats = {
        "renamed_ch": renamed_ch,
        "renamed_prog": renamed_prog,
        "removed_ch": removed,
        "groups": len(main_channel_and_epgid),
    }
    print(f"   ✅ 央视归一化完成: 改组 {stats['groups']} 组，改名 {renamed_ch} 频道，更新 {renamed_prog} 节目，移除 {removed} 空壳")

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='utf-8').decode(), stats

# ===================== 输出校验 =====================
def verify_cctv_output(xml_content, label=""):
    print(f"🔎 校验 {label} 中 CCTV 频道数据覆盖情况...")
    try:
        root = ET.fromstring(xml_content)
    except Exception as e:
        print(f"❌ 校验解析失败: {e}")
        return

    prog_days = defaultdict(set)
    prog_count = defaultdict(int)
    for prog in root.findall('programme'):
        cid = prog.get('channel')
        start = prog.get('start', '')
        if not cid:
            continue
        prog_count[cid] += 1
        if len(start) >= 8:
            prog_days[cid].add(start[:8])

    found_any = False
    for ch in root.findall('channel'):
        cid = ch.get('id')
        if not cid or not cid.upper().startswith('CCTV'):
            continue
        found_any = True
        days = len(prog_days.get(cid, ()))
        cnt = prog_count.get(cid, 0)
        flag = "  ⚠️ 数据不齐（≤1 天）" if days <= 1 else ""
        print(f"      id={cid!r} 天数={days} 节目数={cnt}{flag}")
    if not found_any:
        print("      ⚠️ 没有任何 CCTV-* 频道！")

# ===================== 主函数 =====================
def main():
    print("=" * 60)
    print("🚀 开始处理 EPG 数据")
    print("=" * 60)

    # ================= 阶段 1: 下载 =================
    print("\n📥 阶段 1: 下载原始 EPG...")
    raw_cn = safe_download('https://epg.pw/xmltv/epg_CN.xml')
    raw_tw = safe_download('https://epg.pw/xmltv/epg_TW.xml')
    raw_hk = safe_download('https://epg.pw/xmltv/epg_HK.xml')

    cn = simple_timezone_fix(raw_cn)
    tw = simple_timezone_fix(raw_tw)
    hk = simple_timezone_fix(raw_hk)

    if not cn:
        print("❌ CN EPG 下载失败，无法继续")
        return

    # ================= 阶段 2: 在 CN 里归一化央视 =================
    print("\n🔧 阶段 2: 在 CN EPG 中归一化央视频道（先改 CN，再合并）...")
    alias_map = load_epgid_alias_map()
    cn, stats = normalize_cctv_in_cn(cn, alias_map, only_cctv=True)

    if stats["renamed_ch"] == 0 and stats["removed_ch"] == 0:
        print("   ⚠️⚠️⚠️ 警告: CN EPG 中没有任何央视频道被修改！")
        print("   ⚠️⚠️⚠️ 这意味着最终输出会和原来一样，hash 不会变。")
        print("   ⚠️⚠️⚠️ 请检查下面几点：")
        print("        1. epg_data.json 里是否有 CCTV-* 的 epgid")
        print("        2. CN EPG 里央视频道的 display-name 是否含 'CCTV-数字'")
        print("        3. 是否有同名/重复的央视频道被识别")
    else:
        print(f"   ✅ CN EPG 已修改: {stats}")

    # 校验修改后的 CN
    verify_cctv_output(cn, label="CN EPG（归一化后）")

    # ================= 阶段 3: 合并 =================
    print("\n🔄 阶段 3: 合并 CN + TW + HK...")
    kbro_programs = fetch_kbro_programs(days=7)
    if not kbro_programs:
        print("⚠️ 未抓取到任何节目，退出")
        return
    new_programs_str = format_programs(kbro_programs)

    sources = [('CN', cn)]
    if tw: sources.append(('TW', tw))
    if hk: sources.append(('HK', hk))

    merged_content = simple_merge(sources)

    print("🔄 替换频道 456841 的节目...")
    pattern = r'(<programme channel="456841".*?</programme>\s*)+'
    merged_content = re.sub(pattern, new_programs_str + '\n', merged_content, flags=re.DOTALL)
    print("   ✅ 替换完成")

    # ================= 阶段 4: 保存 =================
    print("\n💾 阶段 4: 保存输出...")
    save_data(merged_content, 'epg_merged.xml')
    cleaned_content = clean_unused_channels(merged_content)
    save_data(cleaned_content, 'epg_merged_clean.xml')
    perfect_content = deduplicate_epg(cleaned_content)
    save_data(perfect_content, 'epg_perfect.xml')

    print("\n✅ 处理完成！")

if __name__ == '__main__':
    main()
