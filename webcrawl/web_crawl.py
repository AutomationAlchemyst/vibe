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
from newspaper import Article, Config # Import Config
# Removed dotenv import as it's not needed when using GitHub Actions secrets
# from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

# Removed load_dotenv("creds.env") call

# Set up logging
# Note: In GitHub Actions, consider if writing to a file is needed, or if stdout/stderr logging is sufficient.
logging.basicConfig(filename="rss_feed.log", level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")

# Load OpenAI API key
# Ensure OPENAI_API_KEY is set in your environment (GitHub Secrets)
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    logging.error("OPENAI_API_KEY environment variable not set.")
    print("ERROR: OPENAI_API_KEY environment variable not set.")
    # Decide if you want to exit here or proceed without OpenAI
    # exit(1) # Uncomment to exit if key is mandatory
    client = None # Set client to None if key is missing
else:
    client = OpenAI(api_key=openai_api_key)

# Setup Google Sheets API
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = os.getenv("SHEET_ID")  # Your sheet ID from environment (GitHub Secrets)
# Ensure credentials2.json exists in the execution environment (created by workflow)
try:
    creds = Credentials.from_service_account_file("credentials2.json", scopes=SCOPES)
    gs_client = gspread.authorize(creds)
    sheet = gs_client.open_by_key(SHEET_ID).sheet1
    logging.info("Google Sheets API authorized successfully.")
    print("INFO: Google Sheets API authorized successfully.") # Added print
except FileNotFoundError:
    logging.error("Failed to authorize Google Sheets API: credentials2.json not found.")
    print("ERROR: Failed to authorize Google Sheets API: credentials2.json not found. Check workflow step.")
    raise # Re-raise to make the workflow fail clearly
except Exception as e:
    logging.error(f"Failed to authorize Google Sheets API: {e}")
    print(f"ERROR: Failed to authorize Google Sheets API: {e}")
    raise e # Re-raise the exception to make it visible

# --- Keyword Definitions ---
keyword_groups = {
    # --- Core MTFA & Specific Entities ---
    "MTFA_Main": [
        "MTFA", "Muslimin Trust Fund Association", "MTFA Singapore",
        # Add specific campaign names if known e.g., "Eid With Ihsan"
    ],
    "Darul_Ihsan_Orphanage": [
        "Darul Ihsan Orphanage", "MTFA Darul Ihsan", "Darul Ihsan Boys", "Darul Ihsan Girls",
        "rumah anak yatim", "orphanage", "displaced children", "vulnerable youths",
         "5 Mattar Road", "23 Wan Tho Ave"
    ],
    "Ihsan_Casket": [
        "Ihsan Casket", "MTFA Ihsan Casket", "burial service", "funeral service",
        "Muslim funeral", "Islamic funeral", "jenazah", "pengurusan jenazah",
        "placenta burial", "free burial", "unclaimed bodies", "ghusl",
        "funeral management course", "info@ihsancasket.com",
    ],
    "Ihsan_Kidney_Care": [
        "Ihsan Kidney Care", "IKC", "MTFA Ihsan Kidney Care", "MTFA dialysis",
        "dialysis centre", "pusat dialisis", "kidney treatment", "rawatan ginjal",
        "buah pinggang", "subsidised dialysis", "Norris Rd dialysis",
    ],
    # --- Core MTFA Service Areas / Future Entities ---
    "MTFA_Financial_Aid": [
        "Ihsan Aid", "MTFA financial assistance", "MTFA welfare aid", "MTFA needy families",
        "MTFA low-income support", "MTFA underprivileged support", "welfareaid@mtfa.org",
        "MTFA zakat", "MTFA fidyah",
    ],
    "MTFA_Education_Support": [
        "Ihsan Education Hub", "MTFA bursary", "MTFA scholarship", "MTFA education award",
        "MTFA student assistance", "MTFA free tuition",
    ],
    "MTFA_Childcare_Service": [ # If MTFA starts this specifically
        "Ihsan Childcare", "MTFA childcare", "MTFA taska", "MTFA tadika", "MTFA nursery",
    ],

    # --- Competitor / Peer Organizations ---
    "Competitor_Kidney_NKF": [
        "NKF", "National Kidney Foundation", "NKF Singapore",
    ],
    "Competitor_Kidney_KDF": [
        "KDF", "Kidney Dialysis Foundation",
    ],
     "Competitor_Kidney_Other": [
         "Tzu Chi kidney", "Tzu Chi dialysis",
     ],
     "Competitor_MuslimAid_RLAF": [
         "RLAF", "Rahmatan Lil Alamin Foundation",
     ],
     "Competitor_MuslimAid_AMP": [
         "AMP Singapore", "AMP financial assistance", "AMP SMEF",
     ],
     "Competitor_ChildrenHome_CSLMCH": [
         "Chen Su Lan Methodist Children's Home", "CSLMCH",
     ],
     "Competitor_ChildrenHome_Melrose": [
         "Melrose Home", "Children's Aid Society",
     ],
     "Competitor_IslamicBurial": [
         "Singapore Muslim Casket", "Persatuan Khairat Kematian Singapura",
         "Takdir Pengurusan Jenazah", "Pengurusan Jenazah Sinaran Baharu"
     ],
     "Competitor_FreeTuition": [
         "Children's Wishing Well",
         "YYD Education Centre",
         "AMP tuition",
         "Tzu Chi Seeds of Hope",
     ],
     "Competitor_Childcare": [
          "MY World Preschool", "Metropolitan YMCA childcare",
          "Canossaville Children and Community Services",
     ],

    # --- AMENDED GROUP for other Social Sector Orgs ---
    "SocialSector_Advocacy_Support": [
        "Humanitarian Organisation for Migration Economics", "H.O.M.E.", # Made "HOME" more specific
        "TWC2", "Transient Workers Count Too",
        "migrant worker support", "foreign worker rights", "domestic worker aid", "migrant workers",
        # "advocacy group", "social justice", # Consider if these are too broad for your needs.
                                             # If they pull too much irrelevant content, you can
                                             # comment them out or make them more specific.
    ],

    # --- General Topics (Use CORE_RELEVANT_GROUPS to control inclusion) ---
    "General_Beneficiaries": ["beneficiary", "penerima bantuan", "asnaf", "recipient", "low-income", "needy", "underprivileged", "vulnerable"],
    "General_Donations": ["donation", "derma", "sumbangan", "infaq", "wakaf", "infak", "fundraising", "pengumpulan dana", "donate", "menyumbang"],
    "General_Zakat": ["zakat", "derma zakat", "bayar zakat"],
    "General_ElderlyCare": ["eldercare", "penjagaan warga emas", "rumah orang tua", "old folks home", "needy elderly"],
    "General_SpecialNeeds": ["special needs", "keperluan khas", "OKU", "disability support"],
    "General_CharitySector": [
        "charity", "charities", "non-profit", "non profit", "NPO", # Common terms
        "philanthropy", "philanthropic", "social impact", "community initiative",
        "foundation grant", # Types of funding
        "NVPC", "National Volunteer & Philanthropy Centre", # Key orgs
        "NCSS", "National Council of Social Service",
        "ComChest", "Community Chest",
        "Temasek Trust", # Major foundations
        "Tote Board",
    ],
}

# --- AMENDED Political Exclusion Keywords ---
POLITICAL_EXCLUSION_KEYWORDS = [
    "political donation", "election", "candidate", "eld", "ge2025",
    "parliamentary seat", "general election", "nomination paper",
    "political party", "campaign fund", "election department",
    "minister", "ministers",                     # Added
    "MP", "Member of Parliament", "MPs",          # Added
    "politician", "politicians",                 # Added
    "government official", "government officials", # Added
    "allegation", "allegations",                 # Added
    "defamation", "libel",                       # Added for legal contexts involving public figures
    "lawsuit against politician",                # Added
    # Add any other specific political roles or situations you want to exclude
    # when they are found in an article also mentioning general donation terms.
]
# --- END OF AMENDMENT ---

# Flat list of all keywords used for highlighting in the email
keywords = [kw for group in keyword_groups.values() for kw in group]

# *** CUSTOMIZE THIS LIST TO CONTROL WHAT GETS SUMMARIZED ***
CORE_RELEVANT_GROUPS = [
    # MTFA Specific Groups (Definitely keep these)
    "MTFA_Main",
    "Darul_Ihsan_Orphanage",
    "Ihsan_Casket",
    "Ihsan_Kidney_Care",
    "MTFA_Financial_Aid",
    "MTFA_Education_Support",
    "MTFA_Childcare_Service",

    # Competitor/Peer Groups (Add the ones you WANT summarized)
    "Competitor_Kidney_NKF",
    "Competitor_Kidney_KDF",
    "Competitor_MuslimAid_RLAF",
    "Competitor_MuslimAid_AMP",
    "Competitor_ChildrenHome_CSLMCH",
    "Competitor_FreeTuition",

    "SocialSector_Advocacy_Support", # To include news about HOME, migrant workers etc.

    # General Topic Groups (Include carefully if desired)
    "General_Beneficiaries",
    "General_Donations",
    "General_Zakat",
    "General_CharitySector",
]

# *** PLACE QUIZ DATA HERE ***
mtfa_quiz_data = [
    {
        "question": "In which year was the Muslimin Trust Fund Association (MTFA) established?",
        "options": ["A) 1946", "B) 1962", "C) 1904"],
        "answer": "C) 1904"
    },
    {
        "question": "What is the name of MTFA's subsidiary providing affordable Islamic burial services?",
        "options": ["A) Ihsan Aid", "B) Ihsan Casket", "C) Darul Ihsan"],
        "answer": "B) Ihsan Casket"
    },
    {
        "question": "MTFA's Ihsan Kidney Care provides subsidised dialysis primarily for which group?",
        "options": ["A) All Singaporeans", "B) Low-income patients", "C) Only MTFA members"],
        "answer": "B) Low-income patients"
    },
    {
        "question": "What percentage of donations (according to the website graphic) is channeled to 'childcare homes'?",
        "options": ["A) 25%", "B) 35%", "C) 5%"],
        "answer": "B) 35%"
    },
    {
        "question": "Which MTFA entity handles funeral management courses?",
        "options": ["A) Darul Ihsan Orphanage", "B) Ihsan Kidney Care", "C) Ihsan Casket"],
        "answer": "C) Ihsan Casket"
    }
]

# --- Utility Functions ---

def sanitize_unicode(text):
    if not isinstance(text, str):
        return ""
    try:
        normalized_text = unicodedata.normalize("NFKD", text)
        return ''.join(c for c in normalized_text if unicodedata.category(c)[0] not in ["C"] or c in ('\n', '\r', '\t'))
    except TypeError:
        logging.warning(f"Could not sanitize non-string input: {type(text)}")
        return ""

def fetch_full_article_content(article_url):
    try:
        config = Config()
        config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
        config.request_timeout = 20
        config.fetch_images = False
        article = Article(article_url, config=config)
        article.download()
        article.parse()
        return article.text
    except Exception as e:
        logging.error(f"Failed to fetch/parse article content from {article_url}: {e}")
        print(f"ERROR: Failed to fetch/parse article content from {article_url}: {e}")
        return ""

def highlight_keywords(summary, keywords_to_highlight):
    processed_summary = summary
    for kw in sorted(keywords_to_highlight, key=len, reverse=True):
        try:
            processed_summary = re.sub(rf"\b({re.escape(kw)})\b", r"<span style='background-color:#fff1a8;'>\1</span>", processed_summary, flags=re.IGNORECASE)
        except re.error as re_err:
            logging.warning(f"Regex error highlighting keyword '{kw}': {re_err}")
            continue
    return processed_summary

def generate_gpt_summary(headline, article_content):
    if not client:
        logging.warning("OpenAI client not initialized. Skipping summary generation.")
        return "Summary generation skipped (OpenAI API key missing)."
    try:
        if not article_content or len(article_content.strip()) < 100:
            logging.warning(f"Content too short or missing for '{headline}'. Skipping summary.")
            return "Summary not available (content too short)."
        content_limit = 3500
        prompt = f"""Analyze the following article regarding a Singaporean context. Summarize its key points in under 100 words, focusing on the **specific details of any mentioned campaign, event, or initiative** (e.g., what is the campaign's goal, who is running it, what are the specific activities or outcomes mentioned?).

        **Avoid generic statements** about platforms (like 'a campaign was launched on Giving.sg'); instead, describe the campaign or initiative itself.

        Prioritize information relevant to charities, social services, non-profits, or community efforts. Exclude purely political news unless it directly impacts this sector.

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
            logging.info(f"Generated Summary for {headline}: {summary_text[:50]}...")
            return summary_text
        else:
            logging.error(f"Invalid or empty response from OpenAI for '{headline}': {response}")
            print(f"ERROR: Invalid or empty response from OpenAI for '{headline}'")
            return "Summary generation failed (invalid API response)."
    except Exception as e:
        logging.error(f"Error summarizing '{headline}' with OpenAI: {e}")
        print(f"ERROR: Error summarizing '{headline}' with OpenAI: {e}")
        return f"Summary generation failed (error: {type(e).__name__})."

def contains_keywords(text, headline, headline_weight=2, content_weight=1, threshold=3):
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
            except re.error as find_err:
                logging.warning(f"Regex error counting keyword '{keyword}': {find_err}. Skipping count.")
                hl_count = 0
                txt_count = 0
            current_score = (hl_count * headline_weight) + (txt_count * content_weight)
            if current_score > 0:
                is_political = False
                if group == "General_Donations":
                    for pk in POLITICAL_EXCLUSION_KEYWORDS:
                        pk_lower = pk.lower()
                        try:
                            if re.search(rf"\b{re.escape(pk_lower)}\b", headline_lower, re.IGNORECASE) or \
                               re.search(rf"\b{re.escape(pk_lower)}\b", text_lower, re.IGNORECASE):
                                is_political = True
                                logging.info(f"Keyword '{keyword}' found in '{headline}', but ignoring due to political term '{pk}'.")
                                print(f"INFO: Keyword '{keyword}' found in '{headline}', but ignoring due to political term '{pk}'.")
                                break
                        except re.error as search_err:
                            logging.warning(f"Regex error checking political keyword '{pk}': {search_err}. Skipping check for this pk.")
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
    try:
        row_data = [
            str(date_str), str(headline), str(summary),
            str(keyword), str(group), str(link)
        ]
        sheet.append_row(row_data)
        logging.info(f"Successfully logged to Google Sheets: {headline[:50]}...")
        print(f"INFO: Successfully logged to Google Sheets: {headline[:50]}...")
    except Exception as e:
        logging.error(f"Failed to log to Google Sheets: {e}")
        print(f"ERROR: Failed to log to Google Sheets: {e}")

def parse_rss_feed(feed_url):
    matched_articles_data = []
    logging.info(f"Processing feed: {feed_url}")
    print(f"INFO: Processing feed: {feed_url}")
    try:
        feed_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
        feed = feedparser.parse(feed_url, agent=feed_agent)
        if feed.bozo:
            logging.warning(f"Feedparser reported issues for {feed_url}: {feed.bozo_exception}")
            print(f"WARNING: Feedparser reported issues for {feed_url}: {feed.bozo_exception}")
        date_threshold = datetime.now() - timedelta(days=3)
        for entry in feed.entries:
            published_date = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try: published_date = datetime(*entry.published_parsed[:6])
                except (ValueError, TypeError, IndexError): pass
            if not published_date and hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                try: published_date = datetime(*entry.updated_parsed[:6])
                except (ValueError, TypeError, IndexError): pass
            if not published_date:
                continue
            if published_date >= date_threshold:
                headline = sanitize_unicode(getattr(entry, 'title', 'No Title'))
                link = sanitize_unicode(getattr(entry, 'link', ''))
                if not link: continue
                rss_summary = sanitize_unicode(getattr(entry, 'summary', ''))
                time.sleep(random.uniform(0.5, 1.5))
                full_article_content = fetch_full_article_content(link)
                content_to_check = full_article_content if len(full_article_content.strip()) >= len(rss_summary.strip()) else rss_summary
                if not content_to_check or len(content_to_check.strip()) < 50:
                    continue
                matched_keyword, keyword_group = contains_keywords(content_to_check, headline)
                if matched_keyword and keyword_group:
                    logging.info(f"Relevant keyword '{matched_keyword}' (Group: {keyword_group}) found in: {headline}")
                    print(f"INFO: Relevant keyword '{matched_keyword}' (Group: {keyword_group}) found in: {headline}")
                    time.sleep(random.uniform(1, 3))
                    summary = generate_gpt_summary(headline, content_to_check)
                    failed_summaries = {"Summary not available (content too short).",
                                        "Summary generation failed (invalid API response).",
                                        "Summary generation skipped (OpenAI API key missing)."}
                    is_failed_summary = summary in failed_summaries or summary.startswith("Summary generation failed")
                    if summary and not is_failed_summary:
                        matched_articles_data.append({
                            "headline": headline, "summary": summary, "link": link,
                            "matched_keyword": matched_keyword, "keyword_group": keyword_group,
                            "published_date": published_date
                        })
                        log_to_google_sheets(
                            published_date.strftime('%Y-%m-%d %H:%M:%S'), headline, summary,
                            matched_keyword, keyword_group, link
                        )
                    else:
                        logging.warning(f"Summary generation failed or skipped for: {headline}. Reason: {summary}")
                        print(f"WARNING: Summary generation failed or skipped for: {headline}. Reason: {summary}")
                elif matched_keyword:
                    pass
    except Exception as e:
        logging.error(f"Unexpected error processing feed {feed_url}: {e}", exc_info=True)
        print(f"ERROR: Unexpected error processing feed {feed_url}: {e}")
    return matched_articles_data

def send_email(matched_articles_data):
    today = datetime.now().strftime('%A, %d %B %Y')
    sheet_link = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}" if SHEET_ID else "#"

    # --- STEP 1: REFINED COLOR PALETTE ---
    brand_primary = "#006a4e"      # MTFA Green for major headings & accents
    brand_secondary = "#0d47a1"    # MTFA Blue for links
    text_primary = "#212529"       # Dark gray for body text, easier on the eyes than pure black
    text_secondary = "#6c757d"     # Lighter gray for metadata, dates, etc.
    border_color = "#dee2e6"       # Light gray for dividers and card borders
    background_light = "#f8f9fa"   # Off-white for the main email body
    background_white = "#ffffff"   # Pure white for cards/content containers
    
    quiz_answer_text = "N/A"
    
    # --- STEP 3: REFINED QUIZ DESIGN ---
    quiz_bg_color = "#eef2f7" # A soft, cool gray-blue
    quiz_html = ""
    if mtfa_quiz_data:
        try:
            quiz_item = random.choice(mtfa_quiz_data)
            quiz_question = quiz_item.get("question", "Quiz question missing.")
            quiz_options = quiz_item.get("options", [])
            quiz_options_html = "<br>".join(quiz_options) if quiz_options else "Options missing."
            quiz_answer_text = quiz_item.get("answer", "Answer missing.")
            quiz_html = f"""
            <div style="background-color: {quiz_bg_color}; border: 1px solid #d0d9e2; padding: 20px 25px; margin-top: 20px; margin-bottom: 40px; border-radius: 8px; text-align: center;">
              <h3 style="color: {brand_primary}; margin-top: 0; margin-bottom: 15px; font-size: 18px; font-weight: 600;">&#10024; MTFA Quick Quiz!</h3>
              <p style="font-size: 15px; color: {text_primary}; line-height: 1.6; margin-bottom: 12px;">{quiz_question}</p>
              <p style="font-size: 14px; color: {text_secondary}; line-height: 1.6;">{quiz_options_html}</p>
              <p style="font-size: 12px; color: #777; margin-top: 15px;"><i>(Answer revealed in the footer!)</i></p>
            </div>
            """
        except (IndexError, KeyError, TypeError) as quiz_err:
            logging.warning(f"Could not select/format quiz item: {quiz_err}")
            quiz_html = ""
            quiz_answer_text = "Error loading quiz"
    else:
        logging.warning("mtfa_quiz_data list is empty. No quiz will be added.")

    categorized_articles = { "MTFA": [], "Competitor": [], "OtherSocialSector": [], "General": [] }
    mtfa_groups = {"MTFA_Main", "Darul_Ihsan_Orphanage", "Ihsan_Casket", "Ihsan_Kidney_Care",
                   "MTFA_Financial_Aid", "MTFA_Education_Support", "MTFA_Childcare_Service"}
    competitor_groups = {"Competitor_Kidney_NKF", "Competitor_Kidney_KDF", "Competitor_Kidney_Other",
                         "Competitor_MuslimAid_RLAF", "Competitor_MuslimAid_AMP",
                         "Competitor_ChildrenHome_CSLMCH", "Competitor_ChildrenHome_Melrose",
                         "Competitor_IslamicBurial", "Competitor_FreeTuition", "Competitor_Childcare"}
    other_social_sector_groups = {"SocialSector_Advocacy_Support"}

    for article in matched_articles_data:
        group = article.get('keyword_group')
        if group in mtfa_groups: categorized_articles["MTFA"].append(article)
        elif group in competitor_groups: categorized_articles["Competitor"].append(article)
        elif group in other_social_sector_groups: categorized_articles["OtherSocialSector"].append(article)
        elif group in CORE_RELEVANT_GROUPS: categorized_articles["General"].append(article)

    for category in categorized_articles:
        categorized_articles[category].sort(key=lambda x: x.get('published_date', datetime.min), reverse=True)

    body_content = ""
    all_keywords_flat = keywords

    def create_category_html(title, articles):
        if not articles: return ""
        # --- STEP 3: REFINED SECTION HEADER ---
        section_html = f'''<h2 style="color: {brand_primary};
                           border-bottom: 1px solid {border_color};
                           padding-bottom: 12px;
                           margin-top: 40px;
                           margin-bottom: 25px;
                           font-size: 22px;
                           font-weight: 600;">
                               &#128226; {title}
                           </h2>'''
        article_blocks = ""
        for article_data in articles:
            summary_text = article_data.get('summary', 'Summary not available.')
            headline_text = article_data.get('headline', 'No Headline')
            link_url = article_data.get('link', '#')
            published_dt = article_data.get('published_date')
            keyword_group_text = article_data.get('keyword_group', 'N/A')
            matched_keyword_text = article_data.get('matched_keyword', 'N/A')
            highlighted_summary = highlight_keywords(summary_text, all_keywords_flat)
            
            # --- STEP 2: REFINED ARTICLE CARD DESIGN ---
            article_blocks += f"""
            <div style="margin-bottom: 25px; padding: 25px; border: 1px solid {border_color}; border-radius: 8px; background-color: {background_white};">
              <h3 style="color: {text_primary}; margin-bottom: 12px; font-size: 18px; font-weight: 600;">{headline_text}</h3>
              
              <p style="font-size: 15px; color: {text_primary}; line-height: 1.6; margin-bottom: 20px;">
                <strong style="color: {brand_primary};">Summary:</strong> {highlighted_summary}
              </p>
              
              <a href="{link_url}" target="_blank" style="display: inline-block; padding: 10px 18px; background-color: {brand_primary}; color: #ffffff; text-decoration: none; border-radius: 6px; font-size: 14px; font-weight: 600;">
                Read Full Article &#8594;
              </a>
              
              <div style="margin-top: 20px; padding-top: 15px; border-top: 1px solid {border_color}; font-size: 12px; color: {text_secondary};">
                  Published: {published_dt.strftime('%d %b %Y, %H:%M') if published_dt else 'N/A'} |
                  Group: {keyword_group_text} |
                  Keyword: {matched_keyword_text}
              </div>
            </div>
            """
        return section_html + article_blocks

    body_content += create_category_html("MTFA & Subsidiary Updates", categorized_articles["MTFA"])
    body_content += create_category_html("Competitor & Peer News", categorized_articles["Competitor"])
    body_content += create_category_html("Other Social Sector News", categorized_articles["OtherSocialSector"])
    body_content += create_category_html("General Topics", categorized_articles["General"])

    if not any(categorized_articles.values()):
        no_news_message = "<p style='text-align: center; font-style: italic; color: #6c757d; padding-top: 20px;'>No relevant news items found matching core criteria in today's crawl.</p>"
        logging.info("No relevant articles found to include in email body after categorization.")
        print("INFO: No relevant articles found to include in email body after categorization.")
        body_content = quiz_html + no_news_message
    else:
        intro_text = f"""
        <p style="font-size: 16px; color: {text_primary}; text-align: center; margin-bottom: 30px;">
            Key news items related to MTFA, competitors, and relevant topics gathered for {today}.
        </p>
        """
        body_content = intro_text + quiz_html + body_content

    # --- FINAL HTML BODY WITH UPDATED STYLES ---
    body = f"""<!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>MTFA Daily Media Report</title>
        <style>
            body, h1, h2, h3, p {{
                margin: 0;
                padding: 0;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol";
            }}
            body {{
                background-color: {background_light};
                -webkit-text-size-adjust: 100%;
                -ms-text-size-adjust: 100%;
            }}
            .email-container {{
                max-width: 750px;
                margin: 40px auto;
                background-color: {background_white};
                border-radius: 8px;
                padding: 30px 40px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.08);
                border-top: 5px solid {brand_primary};
            }}
            a {{
                color: {brand_secondary};
                text-decoration: none;
            }}
            a:hover {{
                text-decoration: underline;
            }}
            img {{
                max-width: 100%;
                height: auto;
                border: 0;
            }}
        </style>
      </head>
      <body style="padding: 20px; margin: 0; background-color: {background_light};">
        <div class="email-container">
          <img src='cid:MTFA_logo' alt='MTFA Logo' style='display:block; margin: 0 auto 25px auto; max-height:70px; border:0;' />
          <h1 style="color: {brand_primary}; text-align: center; margin-bottom: 30px; font-size: 24px; font-weight: bold;">MTFA Daily Media Report</h1>
          {body_content}
          <hr style="border: none; border-top: 1px solid {border_color}; margin: 30px 0;" />
          <p style="font-size: 12px; text-align: center; color: {text_secondary}; line-height: 1.5;">
            <strong style='color:{brand_primary};'>Quiz Answer:</strong> {quiz_answer_text}<br><br>
            Automated report generated by MTFA’s Media Monitor Bot.<br>
            Designed by Ath Thaariq Marthas (MSE-OCE) | Powered by Office of the CEO✨<br>
            <a href="{sheet_link}" target="_blank" style="color: {brand_secondary}; text-decoration: none; font-weight: bold;">📊 View history in Google Sheets</a>
          </p>
        </div>
      </body>
    </html>
    """
    sender_email = os.getenv("SENDER_EMAIL", "ath@mtfa.org")
    email_password = os.getenv("EMAIL_PASSWORD")
    to_email = ["abdulqader@mtfa.org"]
    cc_emails = [
        "officeofed@mtfa.org", "msaifulmtfa@mtfa.org", "mardhiyyah@mtfa.org",
        "juliyah@mtfa.org", "nishani@mtfa.org", "farhan.zohri@mtfa.org", "akram.hanif@mtfa.org", "nur.hanisah@mtfa.org"
    ]
    all_recipients_list = to_email + cc_emails
    if not email_password:
        logging.error("EMAIL_PASSWORD environment variable not set. Cannot send email.")
        print("ERROR: EMAIL_PASSWORD environment variable not set. Cannot send email.")
        return
    if not all_recipients_list:
        logging.error("No recipient emails configured (To or Cc). Cannot send email.")
        print("ERROR: No recipient emails configured (To or Cc). Cannot send email.")
        return

    msg = MIMEMultipart('related')
    msg['From'] = f"MTFA Media Bot <{sender_email}>"
    msg['To'] = ", ".join(to_email)
    msg['Cc'] = ", ".join(cc_emails)
    msg['Subject'] = f"MTFA Daily Media Report - {today}"
    try:
        html_part = MIMEText(body, _subtype='html', _charset='utf-8')
        msg.attach(html_part)
    except Exception as e:
        logging.error(f"Error encoding or attaching HTML body: {e}")
        print(f"ERROR: Error encoding or attaching HTML body: {e}")
        return

    try:
        logo_path = "webcrawl/MTFA_logo.png"
        if os.path.exists(logo_path):
            with open(logo_path, "rb") as img_file:
                logo = MIMEImage(img_file.read())
                logo.add_header('Content-ID', '<MTFA_logo>')
                msg.attach(logo)
                logging.info(f"Successfully attached logo from {logo_path}")
                print(f"INFO: Successfully attached logo from {logo_path}")
        else:
            logging.warning(f"Logo file not found at {logo_path}. Email will be sent without logo.")
            print(f"WARNING: Logo file not found at {logo_path}.")
    except Exception as e:
        logging.error(f"Failed to attach logo image: {e}", exc_info=True)
        print(f"ERROR: Failed to attach logo image: {e}")

    try:
        smtp_server = smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30)
        smtp_server.login(sender_email, email_password)
        smtp_server.send_message(msg)
        smtp_server.quit()
        logging.info(f"Email sent successfully To: {msg['To']} Cc: {msg['Cc']}")
        print(f"INFO: Email sent successfully To: {msg['To']} Cc: {msg['Cc']}")
    except smtplib.SMTPAuthenticationError:
        logging.error("SMTP Authentication Error: Check sender email and password/app password.")
        print("ERROR: SMTP Authentication Error: Check sender email and password/app password.")
    except smtplib.SMTPException as smtp_ex:
        logging.error(f"SMTP Error occurred: {smtp_ex}", exc_info=True)
        print(f"ERROR: SMTP Error occurred: {smtp_ex}")
    except Exception as e:
        logging.error(f"Failed to send email via SMTP: {e}", exc_info=True)
        print(f"ERROR: Failed to send email via SMTP: {e}")

# --- RSS Feed List ---
rss_feeds = [
    # --- Major Singapore News ---
    "https://www.straitstimes.com/news/singapore/rss.xml",
    "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=10416", # CNA Singapore Feed
    "https://www.todayonline.com/feed",
    "https://www.asiaone.com/rss/latest.xml",
    "https://www.tnp.sg/rss.xml", # The New Paper

    # --- Malay Language News ---
    "https://news.google.com/rss/search?q=site:beritaharian.sg", # Google News search for Berita Harian

    # --- Relevant Gov / Statutory Boards ---
    "https://news.google.com/rss/search?q=site:muis.gov.sg", # Google News search for MUIS
    'https://news.google.com/rss/search?q=site:msf.gov.sg+OR+"Ministry+of+Social+and+Family+Development"', # Google News search for MSF

    'https://news.google.com/rss/search?q=site:businesstimes.com.sg+charity+OR+non-profit+OR+philanthropy+OR+"social+impact"',

    # --- Direct MTFA Search ---
    "https://news.google.com/rss/search?q=Muslimin+Trust+Fund+Association+Singapore", # Specific search for MTFA

    # --- Key Competitor/Peer Monitoring (via Google News) ---
    'https://news.google.com/rss/search?q="National+Kidney+Foundation"+NKF+Singapore', # NKF Monitoring
    'https://news.google.com/rss/search?q="Kidney+Dialysis+Foundation"+KDF+Singapore', # KDF Monitoring
    'https://news.google.com/rss/search?q="Rahmatan+Lil+Alamin+Foundation"+RLAF', # RLAF Monitoring
    'https://news.google.com/rss/search?q="Association+of+Muslim+Professionals"+AMP+Singapore', # AMP Monitoring

    # --- AMENDED: The Online Citizen (via Google News) ---
    'https://news.google.com/rss/search?q=site:theonlinecitizen.com+("Humanitarian+Organisation+for+Migration+Economics"+OR+"H.O.M.E."+OR+"migrant+workers"+OR+TWC2+OR+fundraising+OR+advocacy)',
]

# --- Main Execution Logic ---
if __name__ == "__main__":
    logging.info("--- Script Execution Started ---")
    print("--- Script Execution Started ---")
    start_time = time.time()

    all_matched_articles_data = []
    for feed_url in rss_feeds:
        articles_data = parse_rss_feed(feed_url)
        if articles_data:
            all_matched_articles_data.extend(articles_data)
        feed_delay = random.uniform(8, 15)
        logging.info(f"Finished processing {feed_url}. Waiting {feed_delay:.2f} seconds...")
        time.sleep(feed_delay)

    unique_articles_data = []
    seen_headlines = set()
    duplicates_found = 0
    logging.info(f"Collected {len(all_matched_articles_data)} potentially relevant articles. Starting de-duplication...")
    print(f"INFO: Collected {len(all_matched_articles_data)} potentially relevant articles. Starting de-duplication...")
    for article_data in all_matched_articles_data:
        headline_text = article_data.get('headline', '')
        normalized_headline = str(headline_text).lower().strip() if headline_text else ""
        if normalized_headline and normalized_headline not in seen_headlines:
            seen_headlines.add(normalized_headline)
            unique_articles_data.append(article_data)
        elif not normalized_headline:
            logging.warning("Encountered article data with empty headline during de-duplication.")
        else:
            duplicates_found += 1
    logging.info(f"De-duplication complete. Found {duplicates_found} duplicates. Keeping {len(unique_articles_data)} unique articles.")
    print(f"INFO: De-duplication complete. Found {duplicates_found} duplicates. Keeping {len(unique_articles_data)} unique articles.")

    if unique_articles_data:
        logging.info(f"Preparing email with {len(unique_articles_data)} unique relevant articles.")
        print(f"INFO: Preparing email with {len(unique_articles_data)} unique relevant articles.")
        send_email(unique_articles_data)
    else:
        logging.info("No relevant articles found after de-duplication. Sending notification email.")
        print("INFO: No relevant articles found after de-duplication. Sending notification email.")
        send_email([])

    end_time = time.time()
    logging.info(f"--- Script Execution Finished. Total time: {end_time - start_time:.2f} seconds. ---")
    print(f"--- Script Execution Finished. Total time: {end_time - start_time:.2f} seconds. ---")
