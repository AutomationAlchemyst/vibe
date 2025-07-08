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

# --- Basic Configuration ---
# Set up logging to file and console
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[
                        logging.FileHandler("rss_feed.log"),
                        logging.StreamHandler() # Also print logs to console
                    ])

# --- API & Environment Variable Setup ---

# Load OpenAI API key
# Ensure OPENAI_API_KEY is set in your environment (e.g., GitHub Secrets)
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    logging.error("OPENAI_API_KEY environment variable not set. Summarization will be skipped.")
    client = None
else:
    client = OpenAI(api_key=openai_api_key)

# Setup Google Sheets API
# Ensure SHEET_ID is set and credentials2.json is created by your workflow
SHEET_ID = os.getenv("SHEET_ID")
try:
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file("credentials2.json", scopes=SCOPES)
    gs_client = gspread.authorize(creds)
    sheet = gs_client.open_by_key(SHEET_ID).sheet1
    logging.info("Google Sheets API authorized successfully.")
except FileNotFoundError:
    logging.error("Failed to authorize Google Sheets API: credentials2.json not found. Check workflow step.")
    raise
except Exception as e:
    logging.error(f"Failed to authorize Google Sheets API: {e}")
    raise

# --- Keyword Definitions ---
keyword_groups = {
    # --- Core MTFA & Specific Entities ---
    "MTFA_Main": ["MTFA", "Muslimin Trust Fund Association", "MTFA Singapore"],
    "Darul_Ihsan_Orphanage": ["Darul Ihsan Orphanage", "MTFA Darul Ihsan", "rumah anak yatim", "orphanage", "displaced children", "vulnerable youths", "5 Mattar Road", "23 Wan Tho Ave"],
    "Ihsan_Casket": ["Ihsan Casket", "MTFA Ihsan Casket", "burial service", "funeral service", "Muslim funeral", "Islamic funeral", "jenazah", "pengurusan jenazah", "placenta burial", "free burial", "unclaimed bodies", "ghusl", "funeral management course"],
    "Ihsan_Kidney_Care": ["Ihsan Kidney Care", "IKC", "MTFA Ihsan Kidney Care", "MTFA dialysis", "dialysis centre", "pusat dialisis", "kidney treatment", "rawatan ginjal", "buah pinggang", "subsidised dialysis"],
    # --- Core MTFA Service Areas ---
    "MTFA_Financial_Aid": ["Ihsan Aid", "MTFA financial assistance", "MTFA welfare aid", "MTFA needy families", "MTFA low-income support", "MTFA underprivileged support", "welfareaid@mtfa.org", "MTFA zakat", "MTFA fidyah"],
    "MTFA_Education_Support": ["Ihsan Education Hub", "MTFA bursary", "MTFA scholarship", "MTFA education award", "MTFA student assistance", "MTFA free tuition"],
    # --- Competitor / Peer Organizations ---
    "Competitor_Kidney_NKF": ["NKF", "National Kidney Foundation", "NKF Singapore"],
    "Competitor_Kidney_KDF": ["KDF", "Kidney Dialysis Foundation"],
    "Competitor_MuslimAid_RLAF": ["RLAF", "Rahmatan Lil Alamin Foundation"],
    "Competitor_MuslimAid_AMP": ["AMP Singapore", "AMP financial assistance"],
    "Competitor_ChildrenHome_CSLMCH": ["Chen Su Lan Methodist Children's Home", "CSLMCH"],
    "Competitor_FreeTuition": ["Children's Wishing Well", "YYD Education Centre", "AMP tuition", "Tzu Chi Seeds of Hope"],
    # --- Other Social Sector Orgs ---
    "SocialSector_Advocacy_Support": ["Humanitarian Organisation for Migration Economics", "H.O.M.E.", "TWC2", "Transient Workers Count Too", "migrant worker support", "foreign worker rights", "domestic worker aid", "migrant workers"],
    # --- General Topics ---
    "General_Beneficiaries": ["beneficiary", "penerima bantuan", "asnaf", "recipient", "low-income", "needy", "underprivileged", "vulnerable"],
    "General_Donations": ["donation", "derma", "sumbangan", "infaq", "wakaf", "infak", "fundraising", "pengumpulan dana", "donate", "menyumbang"],
    "General_Zakat": ["zakat", "derma zakat", "bayar zakat"],
    "General_CharitySector": ["charity", "charities", "non-profit", "NPO", "philanthropy", "social impact", "community initiative", "foundation grant", "NVPC", "NCSS", "ComChest", "Temasek Trust", "Tote Board"],
}

# Keywords to exclude political articles that might mention "donation"
POLITICAL_EXCLUSION_KEYWORDS = [
    "political donation", "election", "candidate", "eld", "ge2025", "parliamentary seat",
    "general election", "nomination paper", "political party", "campaign fund", "election department",
    "minister", "mp", "member of parliament", "politician", "government official", "allegation",
    "defamation", "libel", "lawsuit against politician",
]

# Flat list of all keywords for highlighting
all_keywords_flat = [kw for group in keyword_groups.values() for kw in group]

# Groups of keywords that are important enough to trigger a summary
CORE_RELEVANT_GROUPS = [
    "MTFA_Main", "Darul_Ihsan_Orphanage", "Ihsan_Casket", "Ihsan_Kidney_Care",
    "MTFA_Financial_Aid", "MTFA_Education_Support", "Competitor_Kidney_NKF",
    "Competitor_Kidney_KDF", "Competitor_MuslimAid_RLAF", "Competitor_MuslimAid_AMP",
    "Competitor_ChildrenHome_CSLMCH", "Competitor_FreeTuition", "SocialSector_Advocacy_Support",
    "General_Beneficiaries", "General_Donations", "General_Zakat", "General_CharitySector",
]

# --- Quiz Data ---
mtfa_quiz_data = [
    {"question": "In which year was the Muslimin Trust Fund Association (MTFA) established?", "options": ["A) 1946", "B) 1962", "C) 1904"], "answer": "C) 1904"},
    {"question": "What is the name of MTFA's subsidiary providing affordable Islamic burial services?", "options": ["A) Ihsan Aid", "B) Ihsan Casket", "C) Darul Ihsan"], "answer": "B) Ihsan Casket"},
    {"question": "MTFA's Ihsan Kidney Care provides subsidised dialysis primarily for which group?", "options": ["A) All Singaporeans", "B) Low-income patients", "C) Only MTFA members"], "answer": "B) Low-income patients"},
]

# --- Utility Functions ---

def sanitize_unicode(text):
    """Normalizes unicode text to remove problematic characters."""
    if not isinstance(text, str): return ""
    try:
        normalized_text = unicodedata.normalize("NFKD", text)
        return ''.join(c for c in normalized_text if unicodedata.category(c)[0] not in ["C"] or c in ('\n', '\r', '\t'))
    except TypeError:
        logging.warning(f"Could not sanitize non-string input: {type(text)}")
        return ""

def fetch_full_article_content(article_url):
    """Fetches article text and top image URL using newspaper3k."""
    try:
        config = Config()
        config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
        config.request_timeout = 20
        config.fetch_images = True  # Enable image fetching
        article = Article(article_url, config=config)
        article.download()
        article.parse()
        return article.text, article.top_image
    except Exception as e:
        logging.error(f"Failed to fetch/parse article from {article_url}: {e}")
        return "", None

def highlight_keywords(summary, keywords_to_highlight):
    """Highlights a list of keywords in a given text string."""
    processed_summary = summary
    for kw in sorted(keywords_to_highlight, key=len, reverse=True):
        try:
            processed_summary = re.sub(rf"\b({re.escape(kw)})\b", r"<span style='background-color:#fff1a8; font-weight: 600;'>\1</span>", processed_summary, flags=re.IGNORECASE)
        except re.error as re_err:
            logging.warning(f"Regex error highlighting keyword '{kw}': {re_err}")
            continue
    return processed_summary

def generate_gpt_summary(headline, article_content):
    """Generates a summary using the OpenAI API."""
    if not client:
        return "Summary generation skipped (OpenAI API key missing)."
    try:
        if not article_content or len(article_content.strip()) < 100:
            logging.warning(f"Content too short for '{headline}'. Skipping summary.")
            return "Summary not available (content too short)."

        content_limit = 3500
        prompt = f"""Analyze the following article from a Singaporean context. Summarize its key points in under 100 words. Focus on the specific details of any mentioned campaign, event, or initiative (e.g., its goal, who is running it, specific activities or outcomes). Prioritize information relevant to charities, social services, or community efforts.

Title: {headline}
Content: {article_content[:content_limit]}"""

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.5
        )
        if response.choices and response.choices[0].message and response.choices[0].message.content:
            summary_text = response.choices[0].message.content.strip()
            logging.info(f"Generated Summary for '{headline[:50]}...'")
            return summary_text
        else:
            logging.error(f"Invalid or empty response from OpenAI for '{headline}': {response}")
            return "Summary generation failed (invalid API response)."
    except Exception as e:
        logging.error(f"Error summarizing '{headline}' with OpenAI: {e}")
        return f"Summary generation failed (error: {type(e).__name__})."

def contains_keywords(text, headline, headline_weight=2, content_weight=1, threshold=3):
    """Scores an article based on keyword presence and returns the best match."""
    score = 0
    best_match_kw = None
    best_match_group = None
    best_match_score = 0
    headline_lower = str(headline).lower() if headline else ""
    text_lower = str(text).lower() if text else ""

    if not headline_lower and not text_lower:
        return None, None

    for group, group_keywords_list in keyword_groups.items():
        for keyword in group_keywords_list:
            kw_lower = keyword.lower()
            try:
                hl_count = len(re.findall(rf"\b{re.escape(kw_lower)}\b", headline_lower, re.IGNORECASE))
                txt_count = len(re.findall(rf"\b{re.escape(kw_lower)}\b", text_lower, re.IGNORECASE))
            except re.error:
                continue

            current_score = (hl_count * headline_weight) + (txt_count * content_weight)
            if current_score > 0:
                # Political exclusion check for general donation terms
                is_political = False
                if group == "General_Donations":
                    for pk in POLITICAL_EXCLUSION_KEYWORDS:
                        try:
                            if re.search(rf"\b{pk.lower()}\b", headline_lower, re.IGNORECASE) or \
                               re.search(rf"\b{pk.lower()}\b", text_lower, re.IGNORECASE):
                                is_political = True
                                logging.info(f"Ignoring '{keyword}' in '{headline}' due to political term '{pk}'.")
                                break
                        except re.error:
                            continue
                
                if not is_political:
                    score += current_score
                    if group in CORE_RELEVANT_GROUPS and current_score > best_match_score:
                        best_match_score = current_score
                        best_match_kw = keyword
                        best_match_group = group

    if score >= threshold and best_match_kw:
        return best_match_kw, best_match_group
    return None, None

def log_to_google_sheets(date_str, headline, summary, keyword, group, link):
    """Appends a new row of data to the configured Google Sheet."""
    try:
        row_data = [str(date_str), str(headline), str(summary), str(keyword), str(group), str(link)]
        sheet.append_row(row_data)
        logging.info(f"Successfully logged to Google Sheets: {headline[:50]}...")
    except Exception as e:
        logging.error(f"Failed to log to Google Sheets: {e}")

# --- Core Logic ---

def parse_rss_feed(feed_url):
    """Processes a single RSS feed to find and summarize relevant articles."""
    matched_articles_data = []
    logging.info(f"Processing feed: {feed_url}")
    try:
        feed_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
        feed = feedparser.parse(feed_url, agent=feed_agent)
        if feed.bozo:
            logging.warning(f"Feedparser reported issues for {feed_url}: {feed.bozo_exception}")

        date_threshold = datetime.now() - timedelta(days=3)
        for entry in feed.entries:
            published_date = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try: published_date = datetime(*entry.published_parsed[:6])
                except (ValueError, TypeError, IndexError): pass
            
            if not published_date: continue
            if published_date < date_threshold: continue

            headline = sanitize_unicode(getattr(entry, 'title', 'No Title'))
            link = sanitize_unicode(getattr(entry, 'link', ''))
            if not link: continue

            time.sleep(random.uniform(0.5, 1.5))
            
            full_article_content, top_image_url = fetch_full_article_content(link)
            
            rss_summary = sanitize_unicode(getattr(entry, 'summary', ''))
            content_to_check = full_article_content if len(full_article_content.strip()) > len(rss_summary.strip()) else rss_summary
            
            if not content_to_check or len(content_to_check.strip()) < 50: continue

            matched_keyword, keyword_group = contains_keywords(content_to_check, headline)
            if matched_keyword and keyword_group:
                logging.info(f"Relevant keyword '{matched_keyword}' (Group: {keyword_group}) found in: {headline}")
                time.sleep(random.uniform(1, 3))
                
                summary = generate_gpt_summary(headline, content_to_check)
                
                failed_summaries = {"Summary not available (content too short).",
                                    "Summary generation failed (invalid API response).",
                                    "Summary generation skipped (OpenAI API key missing)."}
                is_failed_summary = summary in failed_summaries or summary.startswith("Summary generation failed")

                if summary and not is_failed_summary:
                    article_data = {
                        "headline": headline, "summary": summary, "link": link,
                        "matched_keyword": matched_keyword, "keyword_group": keyword_group,
                        "published_date": published_date, "top_image": top_image_url
                    }
                    matched_articles_data.append(article_data)
                    log_to_google_sheets(
                        published_date.strftime('%Y-%m-%d %H:%M:%S'), headline, summary,
                        matched_keyword, keyword_group, link
                    )
                else:
                    logging.warning(f"Summary failed for: {headline}. Reason: {summary}")

    except Exception as e:
        logging.error(f"Unexpected error processing feed {feed_url}: {e}", exc_info=True)
    return matched_articles_data

def send_email(matched_articles_data):
    """Constructs and sends the final HTML email report."""
    today = datetime.now().strftime('%A, %d %B %Y')
    sheet_link = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}" if SHEET_ID else "#"
    
    # --- Email Styling ---
    mtfa_green = "#006a4e"
    mtfa_blue = "#0d47a1"
    body_bg_color = "#f4f7f6"
    container_bg_color = "#ffffff"
    divider_color = "#e9ecef"
    text_color = "#495057"
    heading_color = "#212529"
    
    # --- Quiz Section ---
    quiz_html = ""
    quiz_answer_text = "N/A"
    if mtfa_quiz_data:
        try:
            quiz_item = random.choice(mtfa_quiz_data)
            quiz_question = quiz_item.get("question", "Quiz question missing.")
            quiz_options_html = "<br>".join(quiz_item.get("options", []))
            quiz_answer_text = quiz_item.get("answer", "Answer missing.")
            quiz_html = f"""
            <div style="background-color: #e8f5e9; border: 1px solid #c8e6c9; padding: 20px; margin: 30px 0; border-radius: 8px;">
              <h3 style="color: {mtfa_green}; margin-top: 0; margin-bottom: 12px; font-size: 16px; font-weight: 600;">🤔 MTFA Quick Quiz!</h3>
              <p style="font-size: 15px; color: #333; line-height: 1.6; margin: 0 0 10px 0;">{quiz_question}</p>
              <p style="font-size: 14px; color: #555; line-height: 1.6; margin: 0;">{quiz_options_html}</p>
              <p style="font-size: 12px; color: #555; margin-top: 15px; font-style: italic;">(Answer revealed in the footer!)</p>
            </div>
            """
        except (IndexError, KeyError, TypeError) as e:
            logging.warning(f"Could not format quiz item: {e}")

    # --- Categorize Articles ---
    categorized_articles = { "MTFA": [], "Competitor": [], "OtherSocialSector": [], "General": [] }
    mtfa_groups = {"MTFA_Main", "Darul_Ihsan_Orphanage", "Ihsan_Casket", "Ihsan_Kidney_Care", "MTFA_Financial_Aid", "MTFA_Education_Support"}
    competitor_groups = {k for k in keyword_groups if k.startswith("Competitor_")}
    other_social_sector_groups = {"SocialSector_Advocacy_Support"}

    for article in matched_articles_data:
        group = article.get('keyword_group')
        if group in mtfa_groups: categorized_articles["MTFA"].append(article)
        elif group in competitor_groups: categorized_articles["Competitor"].append(article)
        elif group in other_social_sector_groups: categorized_articles["OtherSocialSector"].append(article)
        elif group in CORE_RELEVANT_GROUPS: categorized_articles["General"].append(article)

    for category in categorized_articles:
        categorized_articles[category].sort(key=lambda x: x.get('published_date', datetime.min), reverse=True)

    # --- HTML Generation for Article Cards ---
    def create_category_html(title, articles):
        if not articles: return ""
        section_html = f'<h2 style="color: {mtfa_green}; border-bottom: 2px solid {divider_color}; padding-bottom: 10px; margin-top: 35px; margin-bottom: 25px; font-size: 20px; font-weight: 600;">{title}</h2>'
        article_blocks = ""
        for article in articles:
            headline = article.get('headline', 'No Headline')
            summary = article.get('summary', 'Summary not available.')
            link = article.get('link', '#')
            pub_date = article.get('published_date')
            group = article.get('keyword_group', 'N/A')
            keyword = article.get('matched_keyword', 'N/A')
            image_url = article.get('top_image')
            
            highlighted_summary = highlight_keywords(summary, all_keywords_flat)
            
            image_html = ""
            if image_url:
                image_html = f'''
                <tr>
                    <td style="padding-bottom: 15px;">
                        <img src="{image_url}" alt="Article Image" style="width: 100%; max-width: 100%; height: auto; display: block; border-radius: 6px 6px 0 0;" onerror="this.style.display='none'">
                    </td>
                </tr>
                '''

            article_blocks += f"""
            <div style="margin-bottom: 25px; border-radius: 8px; background-color: #ffffff; box-shadow: 0 4px 12px rgba(0,0,0,0.05); border: 1px solid {divider_color};">
                <table cellpadding="0" cellspacing="0" border="0" width="100%">
                    {image_html}
                    <tr>
                        <td style="padding: 20px 25px 25px 25px;">
                            <table cellpadding="0" cellspacing="0" border="0" width="100%">
                                <tr>
                                    <td style="padding-bottom: 10px;">
                                        <h3 style="color: {heading_color}; margin: 0; font-size: 18px; font-weight: 600;">{headline}</h3>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding-bottom: 20px;">
                                        <p style="margin: 0; font-size: 15px; color: {text_color}; line-height: 1.65;">{highlighted_summary}</p>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding-bottom: 20px;">
                                        <a href="{link}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: {mtfa_green}; color: #ffffff; text-decoration: none; border-radius: 5px; font-size: 14px; font-weight: bold;">Read Full Article</a>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="font-size: 12px; color: #6c757d; line-height: 1.5; border-top: 1px solid {divider_color}; padding-top: 15px;">
                                        <strong>Published:</strong> {pub_date.strftime('%d %b %Y') if pub_date else 'N/A'}<br>
                                        <strong>Group:</strong> {group} &nbsp;&nbsp;|&nbsp;&nbsp; <strong>Keyword:</strong> {keyword}
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                </table>
            </div>
            """
        return section_html + article_blocks

    body_content = ""
    body_content += create_category_html("MTFA & Subsidiary Updates", categorized_articles["MTFA"])
    body_content += create_category_html("Competitor & Peer News", categorized_articles["Competitor"])
    body_content += create_category_html("Other Social Sector News", categorized_articles["OtherSocialSector"])
    body_content += create_category_html("General Topics", categorized_articles["General"])

    if not any(categorized_articles.values()):
        no_news_message = "<p style='text-align: center; font-style: italic; color: #6c757d; padding: 40px 20px; font-size: 16px;'>No relevant news items found matching core criteria in the last 3 days.</p>"
        body_content = quiz_html + no_news_message
    else:
        intro_text = f"""<p style="font-size: 16px; color: {text_color}; text-align: center; margin-bottom: 0;">
                         Key news items related to MTFA, competitors, and relevant topics.</p>"""
        body_content = intro_text + quiz_html + body_content

    # --- Final HTML Email Assembly ---
    body = f"""<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>MTFA Daily Media Report</title>
        <style>
            body, h1, h2, h3, p {{ margin: 0; padding: 0; font-family: Verdana, Geneva, Tahoma, sans-serif; }}
            body {{ background-color: {body_bg_color}; -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
            .email-container {{ max-width: 750px; margin: 20px auto; background-color: {container_bg_color}; border-radius: 8px; padding: 30px 40px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); border-top: 5px solid {mtfa_green}; }}
            a {{ color: {mtfa_blue}; text-decoration: none;}}
            a:hover {{ text-decoration: underline; }}
            img {{ max-width: 100%; height: auto; border: 0; }}
        </style>
    </head>
    <body style="padding: 20px; margin: 0; background-color: {body_bg_color};">
        <div class="email-container">
            <img src='cid:MTFA_logo' alt='MTFA Logo' style='display:block; margin: 0 auto 20px auto; max-height:65px;' />
            <h1 style="color: {heading_color}; text-align: center; margin-bottom: 10px; font-size: 24px; font-weight: bold;">Daily Media Report</h1>
            <p style="color: {text_color}; text-align: center; margin-bottom: 20px; font-size: 16px;">{today}</p>
            {body_content}
            <hr style="border: none; border-top: 1px solid {divider_color}; margin: 30px 0;" />
            <p style="font-size: 13px; text-align: center; color: #6c757d; line-height: 1.6;">
                <strong style='color:{mtfa_green};'>Quiz Answer:</strong> {quiz_answer_text}<br><br>
                Automated report by MTFA’s Media Monitor Bot.<br>
                Designed by Ath Thaariq Marthas (MSE-OCE) | Powered by Office of the CEO✨<br>
                <a href="{sheet_link}" target="_blank" style="color: {mtfa_blue}; text-decoration: none; font-weight: bold;">📊 View History in Google Sheets</a>
            </p>
        </div>
    </body>
    </html>
    """
    
    # --- Email Sending Logic ---
    sender_email = os.getenv("SENDER_EMAIL")
    email_password = os.getenv("EMAIL_PASSWORD")
    to_email = ["abdulqader@mtfa.org"]
    cc_emails = [
        "officeofed@mtfa.org", "msaifulmtfa@mtfa.org", "mardhiyyah@mtfa.org",
        "juliyah@mtfa.org", "nishani@mtfa.org", "farhan.zohri@mtfa.org", 
        "akram.hanif@mtfa.org", "nur.hanisah@mtfa.org"
    ]
    
    if not all([sender_email, email_password]):
        logging.error("SENDER_EMAIL or EMAIL_PASSWORD environment variables not set. Cannot send email.")
        return

    msg = MIMEMultipart('related')
    msg['From'] = f"MTFA Media Bot <{sender_email}>"
    msg['To'] = ", ".join(to_email)
    msg['Cc'] = ", ".join(cc_emails)
    msg['Subject'] = f"MTFA Media Report - {today}"
    
    msg.attach(MIMEText(body, 'html', 'utf-8'))

    try:
        logo_path = "webcrawl/MTFA_logo.png" # Adjust path as needed
        with open(logo_path, "rb") as img_file:
            logo = MIMEImage(img_file.read())
            logo.add_header('Content-ID', '<MTFA_logo>')
            msg.attach(logo)
            logging.info(f"Successfully attached logo from {logo_path}")
    except FileNotFoundError:
        logging.warning(f"Logo file not found at {logo_path}. Email will be sent without logo.")
    except Exception as e:
        logging.error(f"Failed to attach logo image: {e}")

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, email_password)
            server.send_message(msg, from_addr=sender_email, to_addrs=to_email + cc_emails)
            logging.info("Email sent successfully!")
    except Exception as e:
        logging.error(f"Failed to send email: {e}", exc_info=True)


# --- Main Execution ---
if __name__ == "__main__":
    rss_feeds = [
        "https://www.straitstimes.com/news/singapore/rss.xml",
        "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6311", # CNA Singapore
        "https://www.todayonline.com/singapore/rss",
        "https://berita.mediacorp.sg/rss/singapura", # Berita Mediacorp
        "http://www.asiaone.com/rss/singapore"
    ]
    
    all_matched_articles = []
    for url in rss_feeds:
        all_matched_articles.extend(parse_rss_feed(url))
        time.sleep(random.uniform(1, 2))

    if all_matched_articles:
        send_email(all_matched_articles)
    else:
        logging.info("No new relevant articles found across all feeds. No email will be sent.")
        # Optional: Send an email even if there's no news
        # send_email([]) 
