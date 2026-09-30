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

# ===================== 通用工具 =====================
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

# ===================== 加载 epg_data/epg_data.json =====================
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

# ===================== CCTV 名称解析与模糊匹配 =====================

# 常见的“台号后缀”词，可以出现在 CCTV 台号之后
_CCTV_SUFFIX_WORDS = [
    '综合', '财经', '综艺', '体育赛事', '体育', '电影', '电视剧', '纪录',
    '科教', '戏曲', '社会与法', '新闻', '少儿', '音乐', '奥林匹克',
    '农业农村', '国防军事',
]

# 修饰性尾缀（不含频道含义，仅表示画质/版本），先去这些再解析
_CCTV_DECORATION_RE = re.compile(
    r'\s*(高清|标清|超清|高标清|高清版|高清频道|频道|HD|hd)\s*$'
)


def _strip_decorations(s):
    """反复剥离尾部的画质/版本修饰词，例如 'CCTV-1 综合高清' -> 'CCTV-1 综合'"""
    prev = None
    while prev != s:
        prev = s
        s = _CCTV_DECORATION_RE.sub('', s).strip()
    return s


def _extract_cctv_parts(name):
    """
    从名称中拆出 (num, suffix)。
    - num: CCTV 台号，含可能的 '+'，如 '1' / '5+' / '16'
    - suffix: 台号之后残留的字符串，strip 过，例如 '综合' / '财经' / '体育赛事' / ''
    失败返回 None。
    """
    if not name:
        return None
    m = re.search(r'CCTV[\s\-_]*(\d+)\s*(\+)?', name, re.IGNORECASE)
    if not m:
        return None
    num = m.group(1) + (m.group(2) or '')
    suffix = name[m.end():].strip()
    return num, suffix


def _resolve_epgid(display_name, alias_map):
    """
    把一个 display-name 解析成 epg_data.json 里的 epgid。

    解析顺序：
      1. 精确匹配 alias_map
      2. 逐层剥离尾部修饰词（高清等）后精确匹配
      3. 在 CCTV 台号与数字间加/去连字符后精确匹配
      4. 根据 (CCTV 台号, 后缀) 模糊匹配 epgid：
         4a. 台号相同且后缀完全相同 → 命中
         4b. 台号相同且 epgid 无后缀（如 display='CCTV-1 综合'，epgid='CCTV1'）→ 命中
         4c. display 无后缀时，台号相同的 epgid 取名字最短的一个（例如 display='CCTV-2'，epgid='CCTV-2 财经'）→ 命中
    失败返回 None。
    """
    if not display_name or not alias_map:
        return None

    name = display_name.strip()
    if not name:
        return None

    # ---------- 1. 精确匹配 ----------
    if name in alias_map:
        return alias_map[name]

    # ---------- 2 & 3. 归一化后再匹配 ----------
    def add_hyphen(s):
        return re.sub(r'^(CCTV)[\s\-_]*(\d+)', r'\1-\2', s, flags=re.IGNORECASE)

    def remove_hyphen(s):
        return re.sub(r'^(CCTV)[\s\-_]+(\d+)', r'\1\2', s, flags=re.IGNORECASE)

    seen = set()
    candidates = []
    for base in (name, _strip_decorations(name)):
        for cand in (base, add_hyphen(base), remove_hyphen(base),
                     add_hyphen(_strip_decorations(base)),
                     remove_hyphen(_strip_decorations(base))):
            cand = (cand or '').strip()
            if cand and cand not in seen:
                seen.add(cand)
                candidates.append(cand)

    for cand in candidates:
        epgid = alias_map.get(cand)
        if epgid:
            return epgid

    # ---------- 4. 按 (CCTV 台号, 后缀) 模糊匹配 ----------
    parts = _extract_cctv_parts(name)
    if not parts:
        return None
    disp_num, disp_suffix = parts
    # display 后缀再去一次修饰词，例如 'CCTV-1 综合高清' 的 suffix 会是 '综合'
    disp_suffix = _strip_decorations(disp_suffix)

    all_epgids = set(alias_map.values())

    # 收集所有能解析的 epgid
    epgid_parts = {}
    for epgid in all_epgids:
        if not epgid.upper().startswith('CCTV'):
            continue
        p = _extract_cctv_parts(epgid)
        if p:
            epgid_parts[epgid] = (_strip_decorations(p[1]), p[0])
    # 展开成 (epgid, num, suffix)
    parsed = [(e, num, suf) for e, (suf, num) in epgid_parts.items()]

    # 4a. 后缀完全一致
    for epgid, num, suf in parsed:
        if num == disp_num and suf == disp_suffix:
            return epgid

    # 4b. epgid 无后缀（display 后缀 '综合' 之类落到 'CCTV1' 这种）
    empty_suffix_candidates = []
    for epgid, num, suf in parsed:
        if num == disp_num and suf == '':
            empty_suffix_candidates.append(epgid)
    if empty_suffix_candidates:
        # 优先选形如 'CCTV{n}' 的干净形式；否则按长度排序取最短
        empty_suffix_candidates.sort(
            key=lambda e: (0 if re.fullmatch(rf'CCTV[\-\s]*{re.escape(disp_num)}', e, re.IGNORECASE) else 1,
                           len(e))
        )
        return empty_suffix_candidates[0]

    # 4c. display 无后缀时，允许落到有后缀的 epgid（选名字最短的）
    if not disp_suffix:
        same_num = [(epgid, len(epgid)) for epgid, num, suf in parsed if num == disp_num]
        if same_num:
            same_num.sort(key=lambda x: x[1])
            return same_num[0][0]

    return None


# ===================== 合并同一央视 epgid 下的多个频道 =====================

def _set_first_display_name(channel_elem, new_name):
    """
    把 <channel> 的第一个非空 <display-name> 的文本设为 new_name，
    并把它移动到第一位，方便后续去重时取到它。
    """
    dns = channel_elem.findall('display-name')
    if not dns:
        # 若完全没有 display-name，创建之
        dn = ET.SubElement(channel_elem, 'display-name')
        dn.text = new_name
        return

    target_idx = 0
    for i, dn in enumerate(dns):
        if (dn.text or '').strip():
            target_idx = i
            break

    dns[target_idx].text = new_name

    if target_idx != 0:
        infos = [(dn.tag, dict(dn.attrib), dn.text) for dn in dns]
        for dn in dns:
            channel_elem.remove(dn)
        order = [target_idx] + [i for i in range(len(infos)) if i != target_idx]
        for pos, i in enumerate(order):
            tag, attrib, text = infos[i]
            new_dn = ET.Element(tag, attrib)
            new_dn.text = text
            channel_elem.insert(pos, new_dn)


def merge_cctv_channels_by_epgid(xml_content, alias_map):
    """
    在合并前，对央视频道做特殊处理：
    1. 扫描所有 <channel> 的 <display-name>，通过 _resolve_epgid 解析归属 epgid
    2. 按 epgid 分组，找出同一 epgid 下的所有频道
    3. 统计每个频道挂载的 <programme> 数量，选节目最多的作为主频道
    4. 把同组其他频道的 <programme> 的 channel 属性统一改为主频道的 id
    5. 把主频道的第一位 display-name 改为 epgid，删除同组其他 <channel>
    """
    if not xml_content or not alias_map:
        return xml_content

    print("🔧 合并同一央视 epgid 的多个频道...")

    try:
        root = ET.fromstring(xml_content)
    except Exception as e:
        print(f"❌ 解析 CN EPG 失败: {e}")
        return xml_content

    # ---- 第一步：建立 channel_id -> epgid 的映射 ----
    channel_to_epgid = {}
    channel_elements = {}
    for ch in root.findall('channel'):
        cid = ch.get('id')
        if not cid:
            continue
        channel_elements[cid] = ch
        for dn in ch.findall('display-name'):
            text = (dn.text or '').strip()
            if not text:
                continue
            epgid = _resolve_epgid(text, alias_map)
            if epgid and epgid.upper().startswith('CCTV'):
                channel_to_epgid[cid] = epgid
                # 若 display-name 与最终 epgid 不一致，打印一下便于排查
                if text != epgid:
                    print(f"   🔗 命中: displayName={text!r} -> epgid={epgid!r} (channelId={cid})")
                break

    if not channel_to_epgid:
        print("   ℹ️ 未发现可解析为央视 epgid 的频道")
        return xml_content

    # ---- 第二步：按 epgid 分组 ----
    epgid_to_channel_ids = defaultdict(list)
    for cid, epgid in channel_to_epgid.items():
        epgid_to_channel_ids[epgid].append(cid)

    # ---- 第三步：统计每个频道的 programme 数量 ----
    channel_prog_count = defaultdict(int)
    for prog in root.findall('programme'):
        cid = prog.get('channel')
        if cid:
            channel_prog_count[cid] += 1

    # ---- 第四步：对每组选主频道并合并节目 ----
    removed_channel_ids = set()
    remapped_prog_count = 0

    for epgid, cids in epgid_to_channel_ids.items():
        if len(cids) <= 1:
            # 只有一个频道：只改名，不动节目
            main_cid = cids[0]
            _set_first_display_name(channel_elements[main_cid], epgid)
            continue

        sorted_cids = sorted(cids, key=lambda c: channel_prog_count.get(c, 0), reverse=True)
        main_cid = sorted_cids[0]
        main_ch = channel_elements[main_cid]

        print(f"   📺 {epgid}: {len(cids)} 个频道，主频道 id={main_cid} "
              f"(节目数={channel_prog_count.get(main_cid, 0)})，"
              f"其余: {[(c, channel_prog_count.get(c, 0)) for c in sorted_cids[1:]]}")

        _set_first_display_name(main_ch, epgid)

        # 重定向其他频道下所有 programme
        for other_cid in sorted_cids[1:]:
            for prog in root.findall('programme'):
                if prog.get('channel') == other_cid:
                    prog.set('channel', main_cid)
                    remapped_prog_count += 1
            removed_channel_ids.add(other_cid)

    # ---- 第五步：删除冗余 <channel> ----
    for ch in list(root.findall('channel')):
        cid = ch.get('id')
        if cid in removed_channel_ids:
            root.remove(ch)

    print(f"   ✅ 合并完成：重映射 {remapped_prog_count} 个节目，"
          f"删除 {len(removed_channel_ids)} 个冗余频道")

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='utf-8').decode()

# ===================== 主函数 =====================
def main():
    print("🚀 开始处理EPG数据...")
    raw_cn = safe_download('https://epg.pw/xmltv/epg_CN.xml')
    raw_tw = safe_download('https://epg.pw/xmltv/epg_TW.xml')
    raw_hk = safe_download('https://epg.pw/xmltv/epg_HK.xml')

    cn = simple_timezone_fix(raw_cn)
    tw = simple_timezone_fix(raw_tw)
    hk = simple_timezone_fix(raw_hk)

    # ===== 先处理中国大陆 EPG：把央视多个 ID 合并到 epg_data.json 的 epgid 下 =====
    alias_map = load_epgid_alias_map()
    if cn:
        cn = merge_cctv_channels_by_epgid(cn, alias_map)

    # 抓取 Kbro 节目列表
    kbro_programs = fetch_kbro_programs(days=7)
    if not kbro_programs:
        print("⚠️ 未抓取到任何节目，退出")
        return

    new_programs_str = format_programs(kbro_programs)

    sources = []
    if cn: sources.append(('CN', cn))
    if tw: sources.append(('TW', tw))
    if hk: sources.append(('HK', hk))

    if not sources:
        print("❌ 所有 epg.pw 源下载失败")
        return

    merged_content = simple_merge(sources)

    print("🔄 替换频道 456841 的节目...")
    pattern = r'(<programme channel="456841".*?</programme>\s*)+'
    merged_content = re.sub(pattern, new_programs_str + '\n', merged_content, flags=re.DOTALL)
    print("   ✅ 替换完成")

    save_data(merged_content, 'epg_merged.xml')
    cleaned_content = clean_unused_channels(merged_content)
    save_data(cleaned_content, 'epg_merged_clean.xml')
    perfect_content = deduplicate_epg(cleaned_content)
    save_data(perfect_content, 'epg_perfect.xml')

    print("✅ 处理完成！")

if __name__ == '__main__':
    main()
