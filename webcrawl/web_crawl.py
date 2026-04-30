# -*- coding: utf-8 -*-
import os
import re
import json
import time
import random
import logging
import smtplib
import http.client
import urllib.parse
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

import feedparser
import gspread
from newspaper import Article, Config
from google.oauth2.service_account import Credentials

# --- Configuration & Logging ---
logging.basicConfig(
    filename="rss_feed.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# Gemini API Configuration (Mandatory: Use empty string for key in this environment)
apiKey = "" 
GEMINI_MODEL = "gemini-2.5-flash-preview-09-2025"

# Google Sheets Configuration
SHEET_ID = os.getenv("SHEET_ID", "your_spreadsheet_id_here")
CREDENTIALS_FILE = "credentials2.json"

# --- Keyword Definitions ---
keyword_groups = {
    "MTFA_Main": ["MTFA", "Muslimin Trust Fund Association", "MTFA Singapore"],
    "Darul_Ihsan": ["Darul Ihsan Orphanage", "MTFA Darul Ihsan", "Darul Ihsan Boys", "Darul Ihsan Girls"],
    "Ihsan_Casket": ["Ihsan Casket", "MTFA Ihsan Casket", "Muslim funeral", "jenazah", "pengurusan jenazah"],
    "Ihsan_Kidney_Care": ["Ihsan Kidney Care", "IKC", "MTFA Ihsan Kidney Care", "dialysis centre", "pusat dialisis"],
    "MTFA_Financial_Aid": ["Ihsan Aid", "MTFA financial assistance", "MTFA welfare aid", "MTFA zakat"],
    "Competitor_Kidney": ["NKF", "National Kidney Foundation", "KDF", "Kidney Dialysis Foundation"],
    "Competitor_MuslimAid": ["RLAF", "Rahmatan Lil Alamin Foundation", "AMP Singapore", "Association of Muslim Professionals", "Mendaki", "Yayasan Mendaki"],
    "General_Charity": ["NVPC", "NCSS", "ComChest", "Community Chest", "Temasek Trust", "Tote Board", "social impact", "SG Enable", "VWO", "charity"]
}

EXCLUSION_KEYWORDS = ["coral", "marine life", "power plant", "PacificLight", "ge2025", "election"]

# --- API Interaction ---

def call_gemini_api(prompt):
    """
    Calls Gemini API with mandatory exponential backoff and search grounding.
    """
    host = "generativelanguage.googleapis.com"
    url = f"/v1beta/models/{GEMINI_MODEL}:generateContent?key={apiKey}"
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "systemInstruction": {
            "parts": [{"text": "You are a media intelligence analyst. Summarize articles accurately and objectively."}]
        }
    }
    
    retries = 0
    delays = [1, 2, 4, 8, 16]
    
    while retries < 5:
        try:
            conn = http.client.HTTPSConnection(host)
            headers = {"Content-Type": "application/json"}
            conn.request("POST", url, body=json.dumps(payload), headers=headers)
            response = conn.getresponse()
            data = response.read().decode()
            conn.close()
            
            if response.status == 200:
                result = json.loads(data)
                text = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', "")
                return text
            
            # Retry on rate limits or server errors
            if response.status in [429, 500, 502, 503, 504]:
                time.sleep(delays[retries])
                retries += 1
            else:
                break
        except Exception:
            time.sleep(delays[retries])
            retries += 1
            
    return None

# --- Logic Functions ---

def fetch_content(url):
    """Downloads and parses full article text."""
    try:
        config = Config()
        config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        config.request_timeout = 15
        article = Article(url, config=config)
        article.download()
        article.parse()
        return article.text, article.top_image
    except Exception as e:
        logging.error(f"Error fetching content for {url}: {e}")
        return "", ""

def get_sentiment_and_summary(headline, content):
    """Uses Gemini to generate structured analysis."""
    if not content or len(content) < 50:
        return "Preview unavailable.", "NEUTRAL"

    prompt = f"""
    Analyze this article for a Singaporean non-profit (MTFA).
    1. Summarize key points in under 80 words.
    2. Determine sentiment: [POSITIVE], [NEUTRAL], or [NEGATIVE].
    
    Headline: {headline}
    Content: {content[:3000]}
    
    Format:
    Summary: [Text]
    Sentiment: [TAG]
    """
    
    response = call_gemini_api(prompt)
    if not response:
        return "Summary failed.", "NEUTRAL"
        
    sentiment = "NEUTRAL"
    if "[POSITIVE]" in response.upper(): sentiment = "POSITIVE"
    elif "[NEGATIVE]" in response.upper(): sentiment = "NEGATIVE"
    
    # Robust extraction using Regex to handle varying AI outputs
    summary_match = re.search(r'Summary:\s*(.*?)(?:\n|$)', response, re.IGNORECASE)
    if summary_match:
        summary_part = summary_match.group(1).replace('*', '').strip()
    else:
        # Fallback if AI formatting fails completely
        summary_part = response[:200].replace('*', '') + "..."
        
    return summary_part, sentiment

def check_relevance(text, headline):
    """Checks if article matches keywords and prioritizes MTFA groups."""
    combined = f"{headline} {text}".lower()
    
    if any(ex in combined for ex in EXCLUSION_KEYWORDS):
        return None, None
        
    matched_kw = None
    matched_group = None
        
    for group, kws in keyword_groups.items():
        for kw in kws:
            if re.search(rf"\b{re.escape(kw.lower())}\b", combined):
                # Prioritize MTFA over general/competitor hits
                if any(x in group for x in ["MTFA", "Ihsan", "Darul"]):
                    return kw, group
                # Store competitor/general but keep looking for MTFA
                if not matched_group:
                    matched_kw = kw
                    matched_group = group
                    
    return matched_kw, matched_group

# --- Communication ---

def send_daily_brief(articles):
    """
    Sends a formatted HTML email. If zero hits, sends an audit email only to ath@mtfa.org.
    """
    # Enforce SG Timezone (UTC+8) for accurate date stamping in emails regardless of server location
    sgt_tz = timezone(timedelta(hours=8))
    today = datetime.now(sgt_tz).strftime('%d %b %Y')
    brand_green = "#006a4e"
    brand_blue = "#0d47a1"
    
    # Split articles for layout
    mtfa_hits = [a for a in articles if any(x in a['group'] for x in ["MTFA", "Ihsan", "Darul"])]
    others = [a for a in articles if a not in mtfa_hits]
    
    html_content = ""

    if not articles:
        logging.info("No news hits found. Sending audit email to ath@mtfa.org.")
        html_content = "<p style='text-align:center; color:#555; font-size:16px; padding:40px 20px;'>No relevant news mentions found across tracked feeds today.</p>"
        recipients = ["ath@mtfa.org"]
        cc = []
        subject_suffix = " (No Hits - Audit)"
    else:
        recipients = [
            "abdulqader@mtfa.org",
            "abdulrahman@mtfa.org",
            "jaafar@mtfa.org",
            "faz@mtfa.org",
            "hamzah@mtfa.org",
            "wasim@mtfa.org",
            "sameer@mtfa.org",
            "shaffiqolia@mtfa.org",
            "ferdaus@mtfa.org",
            "adi@mtfa.org",
            "syahiran@mtfa.org",
            "mustaffa@mtfa.org",
            "norhisham@mtfa.org",
            "md.shamir@mtfa.org",
            "madihid@mtfa.org",
            "kamalkarim@mtfa.org",
            "mustaffa@theblackhole.sg",
            "officeofed@mtfa.org",
            "msaifulmtfa@mtfa.org",
            "mardhiyyah@mtfa.org",
            "juliyah@mtfa.org",
            "ath@mtfa.org",
            "farhan.zohri@mtfa.org",
            "akram.hanif@mtfa.org",
            "ikram@mtfa.org",
            "muzdalifah@mtfa.org",
            "shafawati@mtfa.org"
        ]
        cc = []
        subject_suffix = " (🚨 Mention Found)" if mtfa_hits else ""
        
        def format_card(art):
            s_color = {"POSITIVE": "#2e7d32", "NEGATIVE": "#c62828", "NEUTRAL": "#455a64"}.get(art['sentiment'], "#455a64")
            img_tag = f'<img src="{art["image"]}" style="width:100%; height:auto; border-radius:8px 8px 0 0;">' if art['image'] else ""
            
            return f"""
            <div style="background:white; border:1px solid #eee; border-radius:12px; margin-bottom:20px; box-shadow:0 2px 5px rgba(0,0,0,0.05); overflow:hidden;">
                {img_tag}
                <div style="padding:15px;">
                    <span style="font-size:10px; font-weight:bold; color:{s_color}; background:#f0f0f0; padding:2px 8px; border-radius:10px;">{art['sentiment']}</span>
                    <h3 style="margin:10px 0 5px 0; font-size:16px; color:#333;">{art['headline']}</h3>
                    <p style="font-size:14px; color:#555; line-height:1.5;">{art['summary']}</p>
                    <div style="margin-top:10px; font-size:11px; color:#888;">
                        <a href="{art['link']}" style="color:{brand_blue}; text-decoration:none; font-weight:bold;">Read More →</a>
                        <span style="float:right;">{art['group']}</span>
                    </div>
                </div>
            </div>
            """

        sections = [("🚨 MTFA & Subsidiaries Mentions", mtfa_hits), ("🌐 Industry & Peer News", others)]
        for title, collection in sections:
            if collection:
                html_content += f"<h2 style='color:{brand_green}; border-bottom:2px solid {brand_green}; padding-bottom:5px; font-size:18px; margin-top:30px;'>{title}</h2>"
                for art in collection:
                    html_content += format_card(art)

    full_html = f"""
    <html>
    <body style="font-family: sans-serif; background:#f4f7f6; padding:10px; margin:0;">
        <div style="max-width:600px; margin:0 auto; background:white; border-radius:15px; overflow:hidden; border-top:10px solid {brand_green}; box-shadow:0 10px 30px rgba(0,0,0,0.1);">
            <div style="padding:20px; text-align:center; background:#fff;">
                <img src="cid:logo" style="max-height:60px;">
                <h1 style="margin:10px 0 0 0; font-size:22px; color:{brand_green};">MTFA News Brief</h1>
                <p style="font-size:12px; color:#999;">{today} | Daily Briefing</p>
            </div>
            <div style="padding:20px;">
                {html_content}
            </div>
            <div style="background:#f9f9f9; padding:20px; text-align:center; font-size:11px; color:#aaa; border-top:1px solid #eee;">
                This is an automated briefing.
            </div>
        </div>
    </body>
    </html>
    """

    # Email Sending
    sender = os.getenv("SENDER_EMAIL")
    password = os.getenv("EMAIL_PASSWORD")

    msg = MIMEMultipart('related')
    msg['Subject'] = f"MTFA News Brief: {today}{subject_suffix}"
    msg['From'] = f"MTFA Media Bot <{sender}>"
    msg['To'] = ", ".join(recipients)
    if cc:
        msg['Cc'] = ", ".join(cc)
    msg.attach(MIMEText(full_html, 'html'))

    try:
        # Use absolute path to ensure reliability across execution methods (cron, etc)
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webcrawl", "MTFA_logo.png")
        with open(logo_path, "rb") as f:
            img = MIMEImage(f.read())
            img.add_header('Content-ID', '<logo>')
            msg.attach(img)
    except FileNotFoundError:
        logging.warning("Logo file not found. Skipping image attachment.")

    if sender and password:
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(sender, password)
                server.send_message(msg)
                logging.info(f"Email sent successfully with {len(articles)} articles.")
        except Exception as e:
            logging.error(f"Failed to send email: {e}")

# --- Execution ---

if __name__ == "__main__":
    rss_urls = [
        "https://www.straitstimes.com/news/singapore/rss.xml",
        "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=10416",
        "https://news.google.com/rss/search?q=site:beritaharian.sg",
        "https://news.google.com/rss/search?q=%22Muslimin+Trust+Fund+Association%22",
        "https://news.google.com/rss/search?q=%22Mendaki%22+Singapore",
        "https://news.google.com/rss/search?q=%22Yayasan%22+Singapore+charity",
        "https://news.google.com/rss/search?q=%22Community+Chest%22+Singapore+charity",
        "https://news.google.com/rss/search?q=%22SG+Enable%22+Singapore+disability",
        "https://news.google.com/rss/search?q=%22VWO%22+Singapore+charity+non-profit"
    ]
    
    processed_articles = []
    seen_links = set()
    
    # Use timezone-aware limit (UTC) to safely compare with feedparser output
    limit = datetime.now(timezone.utc) - timedelta(hours=24)
    
    # Initialize Sheets and Load History for Deduplication
    try:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gs = gspread.authorize(creds)
        sheet = gs.open_by_key(SHEET_ID).sheet1
        
        # Load the last 200 URLs processed to prevent re-emailing the same links
        try:
            recent_links = sheet.col_values(6)[-200:]
            seen_links.update(recent_links)
        except Exception as e:
            logging.warning(f"Could not load previous links for deduplication: {e}")
    except Exception as e:
        logging.error(f"Sheet init failed: {e}")
        sheet = None

    for feed_url in rss_urls:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:10]: # Check top 10 per feed
            if entry.link in seen_links: continue
            
            try:
                # Fallback to updated_parsed if published_parsed is missing
                time_tuple = getattr(entry, 'published_parsed', getattr(entry, 'updated_parsed', None))
                if time_tuple:
                    # Convert parsed time to timezone-aware UTC datetime
                    pub_date = datetime(*time_tuple[:6]).replace(tzinfo=timezone.utc)
                    if pub_date < limit: continue
                else:
                    # Skip articles without dates entirely
                    continue
            except: continue
            
            content, top_image = fetch_content(entry.link)
            keyword, group = check_relevance(content, entry.title)
            
            if keyword:
                summary, sentiment = get_sentiment_and_summary(entry.title, content)
                article_data = {
                    "headline": entry.title,
                    "summary": summary,
                    "link": entry.link,
                    "sentiment": sentiment,
                    "image": top_image,
                    "group": group,
                    "date": pub_date
                }
                processed_articles.append(article_data)
                seen_links.add(entry.link)
                
                if sheet:
                    try:
                        sheet.append_row([pub_date.strftime('%Y-%m-%d'), entry.title, sentiment, keyword, group, entry.link])
                    except: pass
        
        time.sleep(2) # Politeness delay

    send_daily_brief(processed_articles)
