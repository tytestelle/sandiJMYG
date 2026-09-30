#!/usr/bin/env python3
import requests
import xml.etree.ElementTree as ET
import os
import gzip
from urllib.parse import unquote
import re
import hashlib
from collections import defaultdict
import ssl
import json
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

# ============ 版本标记：用来确认 Actions 跑的是不是新脚本 ============
print("########## SCRIPT VERSION: merge_cctv_v3 ##########")

# ===================== Kbro =====================
def fetch_kbro_programs(days=7):
    print("📡 抓取 Kbro 频道 906 节目...")
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
            print(f"   ⚠️ {date_str} 失败: {e}")
            continue
        if not data or "PROG" not in data:
            continue
        for item in data["PROG"]:
            if item.get("channelid") != "906":
                continue
            start_str = item.get("starttime", "")
            end_str = item.get("endtime", "")
            if not start_str or not end_str:
                continue
            programs.append({
                "title": item.get("programname", ""),
                "start": start_str + " +0800",
                "stop": end_str + " +0800",
                "desc": item.get("programdescr", ""),
                "date": start_str[:8] if len(start_str) >= 8 else ""
            })
    print(f"   ✅ 共 {len(programs)} 个节目")
    return programs

def format_programs(programs):
    lines = []
    for p in programs:
        lines.append(f'  <programme channel="456841" start="{p["start"]}" stop="{p["stop"]}">')
        lines.append(f'    <title lang="zh">{escape(p["title"])}</title>')
        if p["desc"]:
            lines.append(f'    <desc>{escape(p["desc"])}</desc>')
        lines.append(f'    <date>{p["date"]}</date>')
        lines.append('    <audio>')
        lines.append('      <stereo>stereo</stereo>')
        lines.append('    </audio>')
        lines.append('  </programme>')
    return '\n'.join(lines)

# ===================== 基础工具 =====================
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
            print(f"⏭️ 内容无变化: {filename}")
            return
    content_bytes = content.encode('utf-8')
    md5_hash = hashlib.md5(content_bytes).hexdigest()
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    with gzip.open(f'epg_data/{filename}.gz', 'wt', encoding='utf-8') as f:
        f.write(content)
    with open(f'epg_data/{filename}.hash', 'w', encoding='utf-8') as f:
        f.write(md5_hash)
    print(f"💾 已保存: {filename} (MD5: {md5_hash})")

# ===================== 合并 / 清理 / 去重 =====================
def simple_merge(contents):
    print("🔄 合并所有源...")
    merged_root = ET.Element('tv')
    merged_root.set('source-info-name', 'JMYG Merged EPG')
    merged_root.set('generator-info-name', 'JMYG Merger')
    for src_name, content in contents:
        try:
            root = ET.fromstring(content)
            fix_icon_url(root)
            for ch in root.findall('channel'):
                merged_root.append(ch)
            for prog in root.findall('programme'):
                merged_root.append(prog)
            print(f"   ✅ {src_name}: 频道 {len(root.findall('channel'))}, 节目 {len(root.findall('programme'))}")
        except Exception as e:
            print(f"   ❌ {src_name}: {e}")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(merged_root, encoding='utf-8').decode()

def clean_unused_channels(xml_content):
    root = ET.fromstring(xml_content)
    refs = {p.get('channel') for p in root.findall('programme') if p.get('channel')}
    to_remove = [ch for ch in root.findall('channel') if ch.get('id') and ch.get('id') not in refs]
    for ch in to_remove:
        root.remove(ch)
    print(f"🧹 清理无节目频道: 删除 {len(to_remove)}")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='utf-8').decode()

def normalize_channel_name(name):
    if not name:
        return name
    name = re.sub(r'[（(].*?[）)]', '', name)
    name = re.sub(r'[\[【].*?[\]】]', '', name)
    name = re.sub(r'CCTV[- ]?(\d+).*', r'CCTV-\1', name, flags=re.IGNORECASE)
    name = re.sub(r'[\s\-_]*(高清|HD|标清|付费|测试)[\s\-_]*$', '', name, flags=re.IGNORECASE)
    return name.strip()

def deduplicate_epg(xml_content):
    print("🔄 去重...")
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
            id_to_preferred[cid] = norm_to_channel[norm_name].get('id')

    for ch in norm_to_channel.values():
        new_root.append(ch)

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
        key = (preferred_id, start[:12] if len(start) >= 12 else start)
        prog_groups[key].append(prog)

    for key, progs in prog_groups.items():
        if len(progs) == 1:
            best = progs[0]
        else:
            def score(p):
                s = 0
                if p.find('desc') is not None: s += 10
                if p.find('sub-title') is not None: s += 5
                t = p.find('title')
                if t is not None and t.text: s += len(t.text)
                return s
            best = max(progs, key=score)
        best.set('channel', key[0])
        new_root.append(best)

    print(f"   ✅ 去重后频道 {len(new_root.findall('channel'))}, 节目 {len(new_root.findall('programme'))}")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(new_root, encoding='utf-8').decode()

# ===================== 加载 epg_data.json =====================
def load_epgid_alias_map():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    json_path = os.path.join(repo_root, 'epg_data', 'epg_data.json')
    if not os.path.exists(json_path):
        json_path = os.path.join(script_dir, 'epg_data', 'epg_data.json')
    if not os.path.exists(json_path):
        print(f"⚠️ 未找到 epg_data.json: {json_path}")
        return {}
    print(f"📂 加载: {json_path}")
    try:
        with open(json_path, 'r', encoding='utf-8-sig') as f:
            data = json.loads(f.read())
    except Exception as e:
        print(f"❌ 解析失败: {e}")
        return {}
    alias_map = {}
    for item in data.get('epgs', []):
        epgid = (item.get('epgid') or '').strip()
        if not epgid:
            continue
        for alias in (item.get('name') or '').split(','):
            alias = alias.strip()
            if alias:
                alias_map.setdefault(alias, epgid)
    print(f"   ✅ 别名 {len(alias_map)} 条")
    return alias_map

# ===================== 核心：在 CN XML 里合并央视 =====================
CCTV_NUM_RE = re.compile(r'CCTV[\s\-_]*(\d+\+?)', re.IGNORECASE)

def merge_cctv_in_cn(xml_content, alias_map):
    """
    按 CCTV 频道号把同组的多个 channel 合并成一个：
      - 从 epg_data.json 建立「频道号 -> epgid」
      - 遍历所有 channel，从 display-name 提取频道号
      - 同频道号的 channel 按 (节目天数, 节目数) 打分，保留分最高的为主
      - 主 channel 的 id 改成 epgid，display-name 也改成 epgid
      - 同组其它 channel 的 programme 的 channel 属性改成 epgid，然后删除这些 channel
    """
    print("\n🔧 在 CN EPG 里合并央视...")

    root = ET.fromstring(xml_content)

    # 1) 频道号 -> epgid
    num_to_epgid = {}
    for alias, epgid in alias_map.items():
        if not epgid.upper().startswith('CCTV'):
            continue
        m = CCTV_NUM_RE.search(epgid)
        if not m:
            continue
        num = m.group(1).upper()
        if num not in num_to_epgid or len(epgid) < len(num_to_epgid[num]):
            num_to_epgid[num] = epgid
    print(f"   频道号→epgid: {num_to_epgid}")

    # 2) 每个 channel 的节目天数 / 条数
    prog_days = defaultdict(set)
    prog_cnt = defaultdict(int)
    for prog in root.findall('programme'):
        cid = prog.get('channel')
        start = prog.get('start', '')
        if not cid:
            continue
        prog_cnt[cid] += 1
        if len(start) >= 8:
            prog_days[cid].add(start[:8])

    def score(cid):
        return (len(prog_days.get(cid, ())), prog_cnt.get(cid, 0))

    # 3) 按频道号分组
    groups = defaultdict(list)
    for ch in root.findall('channel'):
        cid = ch.get('id')
        if not cid:
            continue
        name = ''
        for dn in ch.findall('display-name'):
            t = (dn.text or '').strip()
            if t:
                name = t
                break
        m = CCTV_NUM_RE.search(name)
        if not m:
            continue
        num = m.group(1).upper()
        if num not in num_to_epgid:
            continue
        groups[num].append(ch)

    if not groups:
        print("   ⚠️ 没有识别到任何央视频道！CN 里可能没有 'CCTV-数字' 的 display-name")
        return xml_content

    # 4) 每组选主 channel
    id_map = {}
    to_remove = []
    main_list = []

    for num, channels in groups.items():
        epgid = num_to_epgid[num]
        channels.sort(key=lambda ch: score(ch.get('id')), reverse=True)
        main = channels[0]
        main_id = main.get('id')

        print(f"   📺 CCTV-{num}: {len(channels)} 个候选 -> epgid={epgid!r}")
        for ch in channels:
            cid = ch.get('id')
            mark = " ★主" if ch is main else ""
            print(f"      id={cid!r} 天数={len(prog_days.get(cid, ()))} 节目数={prog_cnt.get(cid, 0)}{mark}")

        for ch in channels:
            old_id = ch.get('id')
            if old_id != epgid:
                id_map[old_id] = epgid

        for ch in channels[1:]:
            to_remove.append(ch)

        main_list.append((main, epgid))

    # 5) 应用 id 重命名
    for ch in root.findall('channel'):
        cid = ch.get('id')
        if cid in id_map:
            ch.set('id', id_map[cid])
    renamed_prog = 0
    for prog in root.findall('programme'):
        cid = prog.get('channel')
        if cid in id_map:
            prog.set('channel', id_map[cid])
            renamed_prog += 1

    # 6) 删除重复 channel
    removed = 0
    for ch in to_remove:
        root.remove(ch)
        removed += 1

    # 7) 主 channel 的 display-name 改成 epgid
    for main, epgid in main_list:
        for dn in main.findall('display-name'):
            t = (dn.text or '').strip()
            if CCTV_NUM_RE.search(t):
                dn.text = epgid
                break

    print(f"   ✅ 合并 {len(main_list)} 组，重命名 {renamed_prog} 条节目，删除 {removed} 个重复 channel")

    # 8) 校验：打印合并后 CN 里的 CCTV 频道
    print("   📊 CN 里合并后的 CCTV 频道:")
    for ch in root.findall('channel'):
        cid = ch.get('id')
        if not cid or not cid.upper().startswith('CCTV'):
            continue
        print(f"      {cid!r}: 天数={len(prog_days.get(cid, ()))} 节目数={prog_cnt.get(cid, 0)}")

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='utf-8').decode()

# ===================== 主函数 =====================
def main():
    print("\n===== 阶段 1: 下载 =====")
    raw_cn = safe_download('https://epg.pw/xmltv/epg_CN.xml')
    raw_tw = safe_download('https://epg.pw/xmltv/epg_TW.xml')
    raw_hk = safe_download('https://epg.pw/xmltv/epg_HK.xml')

    cn = simple_timezone_fix(raw_cn)
    tw = simple_timezone_fix(raw_tw)
    hk = simple_timezone_fix(raw_hk)

    if not cn:
        print("❌ CN 下载失败")
        return

    print("\n===== 阶段 2: 在 CN 里合并央视 =====")
    alias_map = load_epgid_alias_map()
    cn = merge_cctv_in_cn(cn, alias_map)

    print("\n===== 阶段 3: 合并 + Kbro 替换 =====")
    kbro = fetch_kbro_programs(days=7)
    if not kbro:
        print("⚠️ Kbro 无节目，退出")
        return
    kbro_str = format_programs(kbro)

    sources = [('CN', cn)]
    if tw: sources.append(('TW', tw))
    if hk: sources.append(('HK', hk))
    merged = simple_merge(sources)

    print("🔄 替换频道 456841 的节目...")
    merged = re.sub(r'(<programme channel="456841".*?</programme>\s*)+',
                    kbro_str + '\n', merged, flags=re.DOTALL)

    print("\n===== 阶段 4: 保存 =====")
    save_data(merged, 'epg_merged.xml')
    cleaned = clean_unused_channels(merged)
    save_data(cleaned, 'epg_merged_clean.xml')
    perfect = deduplicate_epg(cleaned)
    save_data(perfect, 'epg_perfect.xml')

    print("\n===== 最终输出里的 CCTV 频道 =====")
    final_root = ET.fromstring(perfect)
    final_days = defaultdict(set)
    final_cnt = defaultdict(int)
    for prog in final_root.findall('programme'):
        cid = prog.get('channel')
        start = prog.get('start', '')
        if not cid:
            continue
        final_cnt[cid] += 1
        if len(start) >= 8:
            final_days[cid].add(start[:8])
    for ch in final_root.findall('channel'):
        cid = ch.get('id')
        if cid and cid.upper().startswith('CCTV'):
            print(f"   {cid!r}: 天数={len(final_days.get(cid, ()))} 节目数={final_cnt.get(cid, 0)}")

    print("\n✅ 全部完成")

if __name__ == '__main__':
    main()
