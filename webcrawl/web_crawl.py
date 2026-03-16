# -*- coding: utf-8 -*-
import random
import os
import smtplib
import feedparser
import logging
import time
import re
import unicodedata
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from openai import OpenAI
from newspaper import Article, Config
import gspread
from google.oauth2.service_account import Credentials

# Set up logging
logging.basicConfig(filename="rss_feed.log", level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")

# Load OpenAI API key
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    logging.error("OPENAI_API_KEY environment variable not set.")
    print("ERROR: OPENAI_API_KEY environment variable not set.")
    client = None
else:
    client = OpenAI(api_key=openai_api_key)

# Setup Google Sheets API
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = os.getenv("SHEET_ID")
try:
    creds = Credentials.from_service_account_file("credentials2.json", scopes=SCOPES)
    gs_client = gspread.authorize(creds)
    sheet = gs_client.open_by_key(SHEET_ID).sheet1
    logging.info("Google Sheets API authorized successfully.")
    print("INFO: Google Sheets API authorized successfully.")
except Exception as e:
    logging.error(f"Failed to authorize Google Sheets API: {e}")
    print(f"ERROR: Failed to authorize Google Sheets API: {e}")
    raise e

# --- Keyword Definitions ---
keyword_groups = {
    "MTFA_Main": ["MTFA", "Muslimin Trust Fund Association", "MTFA Singapore"],
    "Darul_Ihsan_Orphanage": ["Darul Ihsan Orphanage", "MTFA Darul Ihsan", "Darul Ihsan Boys", "Darul Ihsan Girls", "rumah anak yatim", "orphanage", "displaced children", "vulnerable youths", "5 Mattar Road", "23 Wan Tho Ave"],
    "Ihsan_Casket": ["Ihsan Casket", "MTFA Ihsan Casket", "burial service", "funeral service", "Muslim funeral", "Islamic funeral", "jenazah", "pengurusan jenazah", "placenta burial", "free burial", "unclaimed bodies", "ghusl", "funeral management course", "info@ihsancasket.com"],
    "Ihsan_Kidney_Care": ["Ihsan Kidney Care", "IKC", "MTFA Ihsan Kidney Care", "MTFA dialysis", "dialysis centre", "pusat dialisis", "kidney treatment", "rawatan ginjal", "buah pinggang", "subsidised dialysis", "Norris Rd dialysis"],
    "MTFA_Financial_Aid": ["Ihsan Aid", "MTFA financial assistance", "MTFA welfare aid", "MTFA needy families", "MTFA low-income support", "MTFA underprivileged support", "welfareaid@mtfa.org", "MTFA zakat", "MTFA fidyah"],
    "MTFA_Education_Support": ["Ihsan Education Hub", "MTFA bursary", "MTFA scholarship", "MTFA education award", "MTFA student assistance", "MTFA free tuition"],
    "MTFA_Childcare_Service": ["Ihsan Childcare", "MTFA childcare", "MTFA taska", "MTFA tadika", "MTFA nursery"],
    "Competitor_Kidney_NKF": ["NKF", "National Kidney Foundation", "NKF Singapore"],
    "Competitor_Kidney_KDF": ["KDF", "Kidney Dialysis Foundation"],
    "Competitor_MuslimAid_RLAF": ["RLAF", "Rahmatan Lil Alamin Foundation"],
    "Competitor_MuslimAid_AMP": ["AMP Singapore", "AMP financial assistance", "AMP SMEF"],
    "Competitor_ChildrenHome_CSLMCH": ["Chen Su Lan Methodist Children's Home", "CSLMCH"],
    "Competitor_ChildrenHome_Melrose": ["Melrose Home", "Children's Aid Society"],
    "Competitor_IslamicBurial": ["Singapore Muslim Casket", "Persatuan Khairat Kematian Singapura", "Takdir Pengurusan Jenazah", "Pengurusan Jenazah Sinaran Baharu"],
    "Competitor_FreeTuition": ["Children's Wishing Well", "YYD Education Centre", "AMP tuition", "Tzu Chi Seeds of Hope"],
    "Competitor_Childcare": ["MY World Preschool", "Metropolitan YMCA childcare", "Canossaville Children and Community Services"],
    "SocialSector_Advocacy_Support": ["Humanitarian Organisation for Migration Economics", "H.O.M.E.", "TWC2", "Transient Workers Count Too", "migrant worker support", "foreign worker rights", "domestic worker aid", "migrant workers"],
    "General_Beneficiaries": ["beneficiary", "penerima bantuan", "asnaf", "recipient", "low-income", "needy", "underprivileged", "vulnerable"],
    "General_Donations": ["donation", "derma", "sumbangan", "infaq", "wakaf", "infak", "fundraising", "pengumpulan dana", "donate", "menyumbang"],
    "General_Zakat": ["zakat", "derma zakat", "bayar zakat"],
    "General_CharitySector": ["charity", "charities", "non-profit", "non profit", "NPO", "philanthropy", "philanthropic", "social impact", "community initiative", "foundation grant", "NVPC", "NCSS", "ComChest", "Temasek Trust", "Tote Board"],
}

# --- NEW: Specific Exclusion Keywords to prevent environmental/unrelated hits ---
EXCLUSION_KEYWORDS = [
    "coral", "marine life", "power plant", "hydrogen-compatible", "natural gas", 
    "discharge point", "underwater", "environmental study", "PacificLight", 
    "bleaching", "political donation", "election", "candidate", "ge2025"
]

POLITICAL_EXCLUSION_KEYWORDS = ["political donation", "election", "candidate", "eld", "ge2025", "parliamentary seat", "general election", "nomination paper", "political party", "campaign fund", "election department", "minister", "ministers", "MP", "Member of Parliament", "MPs", "politician", "politicians", "government official", "government officials", "allegation", "allegations", "defamation", "libel", "lawsuit against politician"]

CORE_RELEVANT_GROUPS = list(keyword_groups.keys())

mtfa_quiz_data = [
    {"question": "In which year was the Muslimin Trust Fund Association (MTFA) established?", "options": ["A) 1946", "B) 1962", "C) 1904"], "answer": "C) 1904"},
    {"question": "What is the name of MTFA's subsidiary providing affordable Islamic burial services?", "options": ["A) Ihsan Aid", "B) Ihsan Casket", "C) Darul Ihsan"], "answer": "B) Ihsan Casket"},
    {"question": "MTFA's Ihsan Kidney Care provides subsidised dialysis primarily for which group?", "options": ["A) All Singaporeans", "B) Low-income patients", "C) Only MTFA members"], "answer": "B) Low-income patients"},
    {"question": "What percentage of donations (according to the website graphic) is channeled to 'childcare homes'?", "options": ["A) 25%", "B) 35%", "C) 5%"], "answer": "B) 35%"},
    {"question": "Which MTFA entity handles funeral management courses?", "options": ["A) Darul Ihsan Orphanage", "B) Ihsan Kidney Care", "C) Ihsan Casket"], "answer": "C) Ihsan Casket"}
]

keywords = [kw for group in keyword_groups.values() for kw in group]

# --- Functions ---

def fetch_full_article_content(article_url):
    try:
        config = Config()
        agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36'
        ]
        config.browser_user_agent = random.choice(agents)
        config.request_timeout = 20
        article = Article(article_url, config=config)
        article.download()
        article.parse()
        return article.text, article.top_image
    except Exception:
        return "", ""

def highlight_keywords(summary, keywords_to_highlight):
    processed_summary = summary
    for kw in sorted(keywords_to_highlight, key=len, reverse=True):
        processed_summary = re.sub(rf"\b({re.escape(kw)})\b", r"<span style='background-color:#fff1a8; font-weight:bold;'>\1</span>", processed_summary, flags=re.IGNORECASE)
    return processed_summary

def generate_gpt_summary(headline, article_content):
    if not client: return "Summary skipped (API Key Missing).", "NEUTRAL"
    try:
        prompt = f"""Summarize this Singaporean news article in under 90 words. 
        Focus on specific details of mentioned campaigns, events, or initiatives.
        
        At the end of your summary, provide a sentiment tag: [POSITIVE], [NEUTRAL], or [NEGATIVE].

        Title: {headline}
        Content: {article_content[:3500]}"""
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.4
        )
        output = response.choices[0].message.content.strip()
        sentiment = "NEUTRAL"
        if "[POSITIVE]" in output: sentiment = "POSITIVE"
        elif "[NEGATIVE]" in output: sentiment = "NEGATIVE"
        clean_summary = re.sub(r'\[.*?\]', '', output).strip()
        return clean_summary, sentiment
    except:
        return "Summary failed.", "NEUTRAL"

def contains_keywords(text, headline):
    score, best_kw, best_group = 0, None, None
    best_match_score = 0
    h_lower, t_lower = headline.lower(), text.lower()
    full_text_lower = f"{h_lower} {t_lower}"

    # Global Exclusion: If environmental or political noise is found, discard immediately
    if any(re.search(rf"\b{re.escape(ex)}\b", full_text_lower) for ex in EXCLUSION_KEYWORDS):
        return None, None

    for group, group_kws in keyword_groups.items():
        for kw in group_kws:
            kw_l = kw.lower()
            h_count = len(re.findall(rf"\b{re.escape(kw_l)}\b", h_lower, re.IGNORECASE))
            t_count = len(re.findall(rf"\b{re.escape(kw_l)}\b", t_lower, re.IGNORECASE))
            current_score = (h_count * 2) + t_count
            
            if current_score > 0:
                is_political = any(re.search(rf"\b{re.escape(pk.lower())}\b", full_text_lower, re.IGNORECASE) for pk in POLITICAL_EXCLUSION_KEYWORDS)
                if not is_political:
                    # Logic update: Weight MTFA groups higher than general ones
                    is_mtfa_group = "MTFA" in group or "Ihsan" in group or "Darul" in group
                    score += (current_score * 3) if is_mtfa_group else current_score
                    
                    if group in CORE_RELEVANT_GROUPS and current_score > best_match_score:
                        best_match_score = current_score
                        best_kw, best_group = kw, group

    # Strict threshold: If it's just a "General" keyword, we need a higher score to trust it
    final_threshold = 3 if ("MTFA" in str(best_group) or "Ihsan" in str(best_group)) else 6
    return (best_kw, best_group) if score >= final_threshold and best_kw else (None, None)

def send_email(matched_articles_data):
    today = datetime.now().strftime('%A, %d %B %Y')
    brand_green = "#006a4e"
    brand_blue = "#0d47a1"
    bg_light = "#f4f7f6"
    
    total_count = len(matched_articles_data)
    mtfa_hits = sum(1 for a in matched_articles_data if a['keyword_group'] and ("MTFA" in a['keyword_group'] or "Ihsan" in a['keyword_group']))
    sentiment_map = {"POSITIVE": {"bg": "#e8f5e9", "text": "#2e7d32"}, "NEGATIVE": {"bg": "#ffebee", "text": "#c62828"}, "NEUTRAL": {"bg": "#eef2f7", "text": "#455a64"}}

    quiz_item = random.choice(mtfa_quiz_data)
    quiz_html = f"""<div style="background-color: #eef2f7; border: 1px solid #d0d9e2; padding: 20px; margin: 20px 0; border-radius: 12px; text-align: center;">
        <h3 style="color: {brand_green}; margin: 0 0 10px 0;">✨ MTFA Quick Quiz!</h3>
        <p style="font-size: 15px;">{quiz_item['question']}</p>
        <p style="font-size: 14px; color: #666;">{"<br>".join(quiz_item['options'])}</p>
    </div>"""

    content_html = ""
    for art in matched_articles_data:
        s_style = sentiment_map.get(art['sentiment'], sentiment_map["NEUTRAL"])
        highlighted = highlight_keywords(art['summary'], keywords)
        img_html = f'<img src="{art["image"]}" style="width:100%; max-height:180px; object-fit:cover; border-radius:8px 8px 0 0;">' if art["image"] else ""
        content_html += f"""
        <div style="background:white; border:1px solid #ddd; border-radius:12px; margin-bottom:20px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,0.05);">
            {img_html}
            <div style="padding:20px;">
                <span style="background:{s_style['bg']}; color:{s_style['text']}; padding:3px 10px; border-radius:15px; font-size:11px; font-weight:bold;">{art['sentiment']}</span>
                <h3 style="margin:10px 0; color:#333; font-size:18px;">{art['headline']}</h3>
                <p style="font-size:14px; line-height:1.6; color:#444;">{highlighted}</p>
                <div style="margin-top:15px; display:flex; justify-content:space-between; align-items:center; font-size:11px; color:#888;">
                    <a href="{art['link']}" style="color:{brand_blue}; font-weight:bold; text-decoration:none;">Read Full Article →</a>
                    <span>{art['keyword_group']} | {art['date'].strftime('%d %b')}</span>
                </div>
            </div>
        </div>"""

    email_body = f"""<html><body style="background-color:{bg_light}; padding:20px; font-family: 'Segoe UI', Arial, sans-serif;">
        <div style="max-width:700px; margin:0 auto; background:white; border-radius:12px; overflow:hidden; border-top:8px solid {brand_green}; box-shadow:0 10px 25px rgba(0,0,0,0.1);">
            <div style="padding:30px; text-align:center;">
                <img src="cid:MTFA_logo" style="max-height:75px; margin-bottom:15px;">
                <h1 style="color:{brand_green}; margin:0; font-size:24px;">Daily Media Intelligence</h1>
                <p style="color:#888; font-size:14px;">{today} | Prepared by Office of the CEO</p>
            </div>
            <div style="background:{brand_green}; padding:15px; display:flex; justify-content:space-around; text-align:center; color:white;">
                <div><div style="font-size:22px; font-weight:bold;">{total_count}</div><div style="font-size:10px; opacity:0.8;">NEWS HITS</div></div>
                <div><div style="font-size:22px; font-weight:bold;">{mtfa_hits}</div><div style="font-size:10px; opacity:0.8;">MTFA MENTIONS</div></div>
            </div>
            <div style="padding:30px;">{quiz_html} {content_html if matched_articles_data else "<p style='text-align:center; color:#999; padding-top:20px;'>No relevant news found for today.</p>"}</div>
            <div style="padding:25px; background:#f9f9f9; text-align:center; font-size:12px; border-top:1px solid #eee; color:#777;">
                <strong>Quiz Answer:</strong> {quiz_item['answer']}<br><br>
                Designed by Ath Thaariq (MSE-OCE) | <a href="https://docs.google.com/spreadsheets/d/{SHEET_ID}" style="color:{brand_blue};">View Logs</a>
            </div>
        </div>
    </body></html>"""

    sender = os.getenv("SENDER_EMAIL", "ath@mtfa.org")
    pw = os.getenv("EMAIL_PASSWORD")
    to = ["ath@mtfa.org"]
    cc = ["officeofed@mtfa.org"]
    
    msg = MIMEMultipart('related')
    msg['Subject'] = f"MTFA Intelligence Brief: {today}"
    msg['From'] = f"MTFA Media Bot <{sender}>"
    msg['To'] = ", ".join(to)
    msg['Cc'] = ", ".join(cc)
    msg.attach(MIMEText(email_body, 'html'))

    try:
        with open("webcrawl/MTFA_logo.png", "rb") as f:
            img = MIMEImage(f.read())
            img.add_header('Content-ID', '<MTFA_logo>')
            msg.attach(img)
    except: pass

    if pw:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender, pw)
            server.send_message(msg)

# --- Execution ---
if __name__ == "__main__":
    rss_feeds = [
        # --- Major News Outlets ---
        "https://www.straitstimes.com/news/singapore/rss.xml",
        "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=10416",
        "https://www.todayonline.com/feed",
        "https://www.asiaone.com/rss/latest.xml",
        
        # --- Malay Language News ---
        "https://news.google.com/rss/search?q=site:beritaharian.sg",
        
        # --- Philanthropy & Social Sector Focused ---
        "https://news.google.com/rss/search?q=site:businesstimes.com.sg+charity+OR+non-profit+OR+philanthropy",
        
        # --- Relevant Statutory Bodies & MTFA Searches ---
        "https://news.google.com/rss/search?q=site:muis.gov.sg",
        "https://news.google.com/rss/search?q=site:msf.gov.sg+OR+%22Ministry+of+Social+and+Family+Development%22",
        "https://news.google.com/rss?q=Muslimin+Trust+Fund+Association+Singapore",
        
        # --- Competitor Monitoring ---
        "https://news.google.com/rss/search?q=%22National+Kidney+Foundation%22+NKF+Singapore",
        "https://news.google.com/rss/search?q=%22Kidney+Dialysis+Foundation%22+KDF+Singapore",
        "https://news.google.com/rss/search?q=%22Rahmatan+Lil+Alamin+Foundation%22+RLAF",
        "https://news.google.com/rss/search?q=%22Association+of+Muslim+Professionals%22+AMP+Singapore"
    ]
    all_data = []
    seen = set()
    date_limit = datetime.now() - timedelta(days=3)
    
    for url in rss_feeds:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            try:
                pub_date = datetime(*entry.published_parsed[:6])
                if pub_date < date_limit: continue
            except: continue
            
            if entry.link in seen: continue
            content, image = fetch_full_article_content(entry.link)
            kw, group = contains_keywords(content, entry.title)
            
            if kw:
                summary, sentiment = generate_gpt_summary(entry.title, content)
                all_data.append({"headline": entry.title, "summary": summary, "link": entry.link, "sentiment": sentiment, "image": image, "keyword_group": group, "date": pub_date})
                seen.add(entry.link)
                try: sheet.append_row([pub_date.strftime('%Y-%m-%d'), entry.title, summary, kw, group, entry.link])
                except: pass
        
        time.sleep(random.uniform(5, 10))

    send_email(all_data)

