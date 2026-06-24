#!/usr/bin/env python3
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import os
import gzip
from urllib.parse import quote

def safe_download(url):
    """安全下载EPG数据"""
    try:
        print(f"📥 下载: {url}")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        response.encoding = 'utf-8'
        return response.text
    except Exception as e:
        print(f"❌ 下载失败: {e}")
        return None

def fix_icon_url(root):
    """对icon的src进行URL编码，避免台标乱码"""
    for channel in root.findall('channel'):
        icon = channel.find('icon')
        if icon is not None and 'src' in icon.attrib:
            original_url = icon.attrib['src']
            parts = original_url.split('/')
            encoded_parts = [quote(p) for p in parts]
            icon.attrib['src'] = '/'.join(encoded_parts)

def fix_display_name(root):
    """确保display-name中文安全"""
    for channel in root.findall('channel'):
        for name in channel.findall('display-name'):
            if name.text:
                name.text = name.text.strip()

def merge_epg_data(contents):
    """
    合并多个EPG数据源
    contents: list of (source_name, xml_content)
    """
    print("🔄 合并EPG数据...")
    
    merged_root = ET.Element('tv')
    merged_root.set('source-info-name', 'JMYG Merged EPG')
    merged_root.set('source-info-url', 'https://github.com/9602894/JMYG')
    merged_root.set('generator-info-name', 'JMYG EPG Merger')
    
    added_channels = set()
    
    for source_name, content in contents:
        try:
            root = ET.fromstring(content)
            fix_icon_url(root)
            fix_display_name(root)
            
            for channel in root.findall('channel'):
                channel_id = channel.get('id')
                if channel_id and channel_id not in added_channels:
                    merged_root.append(channel)
                    added_channels.add(channel_id)
            
            for programme in root.findall('programme'):
                merged_root.append(programme)
                
            print(f"✅ 已合并 {source_name} 数据")
        except Exception as e:
            print(f"❌ 处理 {source_name} 数据时出错: {e}")
    
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(merged_root, encoding='utf-8').decode()

def simple_timezone_fix(xml_content):
    """时区修复为东八区"""
    if xml_content:
        return xml_content.replace('+0000', '+0800').replace('UTC', '+0800')
    return xml_content

def save_data(content, filename):
    """保存XML及压缩版本"""
    os.makedirs('epg_data', exist_ok=True)
    
    with open(f'epg_data/{filename}', 'w', encoding='utf-8') as f:
        f.write(content)
    
    with gzip.open(f'epg_data/{filename}.gz', 'wt', encoding='utf-8') as f:
        f.write(content)
    
    print(f"💾 已保存: {filename}")

def main():
    print("🚀 开始处理EPG数据...")
    
    # 下载三个数据源
    raw_cn = safe_download('https://epg.pw/xmltv/epg_CN.xml')
    raw_tw = safe_download('https://epg.pw/xmltv/epg_TW.xml')
    raw_hk = safe_download('https://epg.pw/xmltv/epg_HK.xml')
    
    # 时区修复
    cn_content = simple_timezone_fix(raw_cn)
    tw_content = simple_timezone_fix(raw_tw)
    hk_content = simple_timezone_fix(raw_hk)
    
    # 构建有效源列表
    sources = []
    if cn_content:
        sources.append(('CN', cn_content))
    if tw_content:
        sources.append(('TW', tw_content))
    if hk_content:
        sources.append(('HK', hk_content))
    
    if sources:
        merged_content = merge_epg_data(sources)
        if merged_content:
            save_data(merged_content, 'epg_merged.xml')
            print("✅ EPG数据合并完成！")
        else:
            print("❌ 合并失败，使用第一个有效源作为备用")
            save_data(sources[0][1], 'epg_merged.xml')
    else:
        print("❌ 所有数据源下载失败，无法生成EPG")

    print("🎉 EPG处理完成！")

if __name__ == '__main__':
    main()
