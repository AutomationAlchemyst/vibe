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

    # --- START OF AMENDMENT: New group for other Social Sector Orgs ---
    "SocialSector_Advocacy_Support": [
        "HOME", "Humanitarian Organisation for Migration Economics", "H.O.M.E.",
        "TWC2", "Transient Workers Count Too",
        "migrant worker support", "foreign worker rights", "domestic worker aid", "migrant workers",
        "advocacy group", "social justice",
        # Add other specific orgs or causes MTFA wants to be aware of, e.g., AWARE if relevant
        # "AWARE Singapore",
    ],
    # --- END OF AMENDMENT ---

    # --- General Topics (Use CORE_RELEVANT_GROUPS to control inclusion) ---
    "General_Beneficiaries": ["beneficiary", "penerima bantuan", "asnaf", "recipient", "low-income", "needy", "underprivileged", "vulnerable"],
    # Removed 'giving.sg' keyword
    "General_Donations": ["donation", "derma", "sumbangan", "infaq", "wakaf", "infak", "fundraising", "pengumpulan dana", "donate", "menyumbang"],
    "General_Zakat": ["zakat", "derma zakat", "bayar zakat"],
    "General_ElderlyCare": ["eldercare", "penjagaan warga emas", "rumah orang tua", "old folks home", "needy elderly"],
    "General_SpecialNeeds": ["special needs", "keperluan khas", "OKU", "disability support"],
    # Added General Charity Sector group
    "General_CharitySector": [
        "charity", "charities", "non-profit", "non profit", "NPO", # Common terms
        "philanthropy", "philanthropic", "social impact", "community initiative",
        "foundation grant", # Types of funding
        "NVPC", "National Volunteer & Philanthropy Centre", # Key orgs
        "NCSS", "National Council of Social Service",
        "ComChest", "Community Chest",
        "Temasek Trust", # Major foundations
        "Tote Board",
        # Add other relevant sector terms
    ],
}

# >>> START OF CHANGE: Add Political Exclusion Keywords <<<
POLITICAL_EXCLUSION_KEYWORDS = [
    "political donation", "election", "candidate", "eld", "ge2025",
    "parliamentary seat", "general election", "nomination paper",
    "political party", "campaign fund", "election department"
    # Add any other relevant political terms
]
# >>> END OF CHANGE <<<

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
    "MTFA_Childcare_Service", # Keep if/when relevant

    # Competitor/Peer Groups (Add the ones you WANT summarized)
    "Competitor_Kidney_NKF",         # Example: Include NKF news
    "Competitor_Kidney_KDF",         # Example: Include KDF news
    "Competitor_MuslimAid_RLAF",     # Example: Include RLAF news
    "Competitor_MuslimAid_AMP",      # Example: Include AMP news
    "Competitor_ChildrenHome_CSLMCH",# Example: Add if needed
    "Competitor_FreeTuition",        # Example: Add if needed

    # --- START OF AMENDMENT: Add new group to CORE ---
    "SocialSector_Advocacy_Support", # To include news about HOME, migrant workers etc.
    # --- END OF AMENDMENT ---

    # General Topic Groups (Include carefully if desired)
    "General_Beneficiaries",         # May include broad/unrelated "recipient" news
    "General_Donations",             # May include broad donation news (will be filtered for political)
    "General_Zakat",                 # If general Zakat news is useful
    "General_CharitySector",         # Include articles matched by general charity terms
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
    # ... Add more quiz items ...
]

# --- Utility Functions ---

def sanitize_unicode(text):
    # Normalize unicode characters and remove surrogate pairs if any slip through
    if not isinstance(text, str): # Handle potential non-string input gracefully
        return ""
    try:
        # Normalize unicode characters to their canonical equivalents
        normalized_text = unicodedata.normalize("NFKD", text)
        # Remove control characters, keeping common whitespace like newline
        return ''.join(c for c in normalized_text if unicodedata.category(c)[0] not in ["C"] or c in ('\n', '\r', '\t'))
    except TypeError:
        logging.warning(f"Could not sanitize non-string input: {type(text)}")
        return ""


def fetch_full_article_content(article_url):
    # Fetches and parses article using newspaper3k with User-Agent
    try:
        config = Config()
        # Use a common browser user agent
        config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
        config.request_timeout = 20 # Increased timeout slightly
        config.fetch_images = False # Don't download images

        article = Article(article_url, config=config)
        article.download()
        # Optional: Basic status code check if possible (newspaper3k might raise exceptions on failure anyway)
        # if article.download_state == 2: # 2 often means success
        article.parse()
        # else:
        #     logging.warning(f"Article download failed for {article_url}, state: {article.download_state}")
        #     return ""
        return article.text
    except Exception as e:
        # Catch specific newspaper exceptions if known, otherwise general exception
        logging.error(f"Failed to fetch/parse article content from {article_url}: {e}")
        print(f"ERROR: Failed to fetch/parse article content from {article_url}: {e}") # Add print
        return ""


def highlight_keywords(summary, keywords_to_highlight):
    # Highlights keywords in the summary text using HTML span tags
    processed_summary = summary
    # Sort by length descending to match longer phrases first (e.g., "National Kidney Foundation" before "NKF")
    for kw in sorted(keywords_to_highlight, key=len, reverse=True):
        try:
            # Use word boundaries (\b) to avoid matching parts of words (e.g., match "AMP" not "campaign")
            # Escape special regex characters in the keyword itself
            # Case-insensitive matching
            processed_summary = re.sub(rf"\b({re.escape(kw)})\b", r"<span style='background-color:#fff1a8;'>\1</span>", processed_summary, flags=re.IGNORECASE) # Softer yellow
        except re.error as re_err:
            logging.warning(f"Regex error highlighting keyword '{kw}': {re_err}")
            continue # Skip problematic keyword
    return processed_summary


def generate_gpt_summary(headline, article_content):
    # Generates summary using OpenAI API
    # Check if OpenAI client was initialized (API key provided)
    if not client:
        logging.warning("OpenAI client not initialized. Skipping summary generation.")
        return "Summary generation skipped (OpenAI API key missing)."
    try:
        # Basic check for meaningful content length
        if not article_content or len(article_content.strip()) < 100:
            logging.warning(f"Content too short or missing for '{headline}'. Skipping summary.")
            return "Summary not available (content too short)."

        content_limit = 3500 # Keep or adjust as needed

        # >>> START OF PROMPT CHANGE <<<
        # Modified prompt to focus on campaign specifics as per feedback
        prompt = f"""Analyze the following article regarding a Singaporean context. Summarize its key points in under 100 words, focusing on the **specific details of any mentioned campaign, event, or initiative** (e.g., what is the campaign's goal, who is running it, what are the specific activities or outcomes mentioned?).

        **Avoid generic statements** about platforms (like 'a campaign was launched on Giving.sg'); instead, describe the campaign or initiative itself.

        Prioritize information relevant to charities, social services, non-profits, or community efforts. Exclude purely political news unless it directly impacts this sector.

        Title: {headline}

        Content: {article_content[:content_limit]}"""
        # >>> END OF PROMPT CHANGE <<<

        response = client.chat.completions.create(
            model="gpt-4o", # Or your preferred model
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150, # Limit response length
            temperature=0.5 # Adjust for desired creativity/factualness
        )
        # Check if response is valid and contains content
        if response.choices and response.choices[0].message and response.choices[0].message.content:
            summary_text = response.choices[0].message.content.strip()
            logging.info(f"Generated Summary for {headline}: {summary_text[:50]}...") # Log first part
            return summary_text
        else:
            logging.error(f"Invalid or empty response from OpenAI for '{headline}': {response}")
            print(f"ERROR: Invalid or empty response from OpenAI for '{headline}'") # Add print
            return "Summary generation failed (invalid API response)."

    except Exception as e:
        logging.error(f"Error summarizing '{headline}' with OpenAI: {e}")
        print(f"ERROR: Error summarizing '{headline}' with OpenAI: {e}") # Add print
        # Provide more context in the error message returned
        return f"Summary generation failed (error: {type(e).__name__})."

# >>> START OF CHANGE: Modify contains_keywords function <<<
def contains_keywords(text, headline, headline_weight=2, content_weight=1, threshold=3):
    # Checks if text/headline contain keywords above a threshold score
    # Returns the best matching relevant keyword and group, or None
    score = 0
    best_match_kw = None
    best_match_group = None
    best_match_score = 0

    # Ensure inputs are strings and lowercase them
    headline_lower = str(headline).lower() if headline else ""
    text_lower = str(text).lower() if text else ""

    # If no text content, cannot match keywords
    if not headline_lower and not text_lower:
        return None, None

    for group, group_keywords_list in keyword_groups.items(): # Renamed to avoid conflict
        for keyword in group_keywords_list:
            kw_lower = keyword.lower()
            # Use regex findall for more accurate counting of whole words, handle potential errors
            try:
                hl_count = len(re.findall(rf"\b{re.escape(kw_lower)}\b", headline_lower, re.IGNORECASE))
                txt_count = len(re.findall(rf"\b{re.escape(kw_lower)}\b", text_lower, re.IGNORECASE))
            except re.error as find_err:
                logging.warning(f"Regex error counting keyword '{keyword}': {find_err}. Skipping count.")
                hl_count = 0
                txt_count = 0

            current_score = (hl_count * headline_weight) + (txt_count * content_weight)

            if current_score > 0:
                # --- START political exclusion logic ---
                is_political = False
                # Only apply exclusion check if the match is from General_Donations group
                if group == "General_Donations":
                    # Check if any political exclusion keyword exists in headline or text
                    for pk in POLITICAL_EXCLUSION_KEYWORDS:
                        pk_lower = pk.lower()
                        try:
                            # Simple check if the political keyword exists anywhere (case-insensitive, whole word)
                            # Using re.search for efficiency (stops at first find)
                            if re.search(rf"\b{re.escape(pk_lower)}\b", headline_lower, re.IGNORECASE) or \
                               re.search(rf"\b{re.escape(pk_lower)}\b", text_lower, re.IGNORECASE):
                                is_political = True
                                logging.info(f"Keyword '{keyword}' found in '{headline}', but ignoring due to political term '{pk}'.")
                                print(f"INFO: Keyword '{keyword}' found in '{headline}', but ignoring due to political term '{pk}'.") # Add print
                                break # Found a political term, no need to check others for this keyword match
                        except re.error as search_err:
                            logging.warning(f"Regex error checking political keyword '{pk}': {search_err}. Skipping check for this pk.")
                            continue # Skip problematic political keyword

                # --- END political exclusion logic ---

                # If it's not a political article (or not from General_Donations group), proceed to score
                if not is_political:
                    score += current_score
                    # Check if this match belongs to a CORE group and has the highest score so far for such groups
                    if group in CORE_RELEVANT_GROUPS and current_score > best_match_score:
                        best_match_score = current_score
                        best_match_kw = keyword
                        best_match_group = group
                # If it *was* political, we simply don't add its score or consider it for best_match

    # Check overall score threshold *after* evaluating all keywords
    # Return the best match found among relevant (CORE_RELEVANT_GROUPS), non-excluded keywords IF threshold met
    if score >= threshold and best_match_kw:
        return best_match_kw, best_match_group

    # If threshold not met, or no relevant match found after exclusions
    return None, None
# >>> END OF CHANGE <<<


def log_to_google_sheets(date_str, headline, summary, keyword, group, link):
    # Appends a row to the configured Google Sheet
    try:
        # Ensure all parts are strings before appending
        row_data = [
            str(date_str), str(headline), str(summary),
            str(keyword), str(group), str(link)
        ]
        sheet.append_row(row_data)
        logging.info(f"Successfully logged to Google Sheets: {headline[:50]}...")
        print(f"INFO: Successfully logged to Google Sheets: {headline[:50]}...") # Add print
    except Exception as e:
        logging.error(f"Failed to log to Google Sheets: {e}")
        print(f"ERROR: Failed to log to Google Sheets: {e}") # Add print


def parse_rss_feed(feed_url):
    # Parses a single RSS feed and returns relevant article data
    matched_articles_data = []
    logging.info(f"Processing feed: {feed_url}")
    print(f"INFO: Processing feed: {feed_url}") # Add print
    try:
        # Add a User-Agent to feedparser requests too
        feed_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
        # Consider adding timeout to parse request if possible (depends on feedparser version/config)
        feed = feedparser.parse(feed_url, agent=feed_agent) # request_headers={'User-Agent': feed_agent} might also work

        if feed.bozo: # Check if feedparser encountered issues
            # Log warning, but continue processing entries if possible
            logging.warning(f"Feedparser reported issues for {feed_url}: {feed.bozo_exception}")
            print(f"WARNING: Feedparser reported issues for {feed_url}: {feed.bozo_exception}") # Add print

        # Use timezone-aware datetime if possible, otherwise assume UTC or local time consistently
        # For simplicity here, using naive datetime - ensure comparison logic is consistent
        date_threshold = datetime.now() - timedelta(days=3) # Check articles from the last 3 days

        for entry in feed.entries:
            published_date = None
            # Try finding a usable date, preferring 'published_parsed'
            # Check attribute existence before accessing
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try: published_date = datetime(*entry.published_parsed[:6])
                except (ValueError, TypeError, IndexError): pass # Catch potential errors during tuple unpacking
            if not published_date and hasattr(entry, 'updated_parsed') and entry.updated_parsed: # Fallback to 'updated_parsed'
                try: published_date = datetime(*entry.updated_parsed[:6])
                except (ValueError, TypeError, IndexError): pass

            # Skip entry if no valid date could be parsed
            if not published_date:
                # logging.warning(f"No valid date found for entry: {getattr(entry, 'title', 'N/A')} in {feed_url}") # Can be verbose
                continue # Skip this entry

            # Check if the article is recent enough
            if published_date >= date_threshold:
                # Use getattr for safer access to potentially missing attributes
                headline = sanitize_unicode(getattr(entry, 'title', 'No Title'))
                link = sanitize_unicode(getattr(entry, 'link', ''))
                if not link: continue # Skip if no link

                # Prefer full article content if fetched successfully, fallback to RSS summary
                rss_summary = sanitize_unicode(getattr(entry, 'summary', ''))
                # Add slight delay before fetching full content
                time.sleep(random.uniform(0.5, 1.5))
                full_article_content = fetch_full_article_content(link) # Handles its own sanitization

                # Use the longer content source for keyword checking
                content_to_check = full_article_content if len(full_article_content.strip()) >= len(rss_summary.strip()) else rss_summary

                if not content_to_check or len(content_to_check.strip()) < 50: # Add minimum length check for content
                    # logging.info(f"Content too short for reliable keyword check: {headline}") # Can be verbose
                    continue # Skip if content is too short

                # Check for keywords (this function now includes the political filter)
                matched_keyword, keyword_group = contains_keywords(content_to_check, headline)

                # Process only if a relevant keyword matched AND it belongs to a group we care about (CORE_RELEVANT_GROUPS)
                if matched_keyword and keyword_group: # Check keyword_group is not None
                    logging.info(f"Relevant keyword '{matched_keyword}' (Group: {keyword_group}) found in: {headline}")
                    print(f"INFO: Relevant keyword '{matched_keyword}' (Group: {keyword_group}) found in: {headline}") # Add print

                    # Add slight delay before potentially costly OpenAI call
                    time.sleep(random.uniform(1, 3)) # Random delay between 1-3 seconds
                    summary = generate_gpt_summary(headline, content_to_check)

                    # Define summary failure conditions more clearly
                    failed_summaries = {"Summary not available (content too short).",
                                        "Summary generation failed (invalid API response).",
                                        "Summary generation skipped (OpenAI API key missing)."}
                    is_failed_summary = summary in failed_summaries or summary.startswith("Summary generation failed")

                    # Only proceed if summary generation was successful
                    if summary and not is_failed_summary:
                        matched_articles_data.append({
                            "headline": headline, "summary": summary, "link": link,
                            "matched_keyword": matched_keyword, "keyword_group": keyword_group,
                            "published_date": published_date
                        })
                        # Log to Google Sheets
                        log_to_google_sheets(
                            published_date.strftime('%Y-%m-%d %H:%M:%S'), headline, summary,
                            matched_keyword, keyword_group, link
                        )
                    else:
                        # Log reason for failure/skip
                        logging.warning(f"Summary generation failed or skipped for: {headline}. Reason: {summary}")
                        print(f"WARNING: Summary generation failed or skipped for: {headline}. Reason: {summary}") # Add print

                elif matched_keyword:
                    # This case should ideally not be reached if keyword_group is None when political filter applied,
                    # but kept for logging just in case. The political filter logging happens inside contains_keywords.
                    # logging.info(f"Keyword '{matched_keyword}' found in '{headline}' but group '{keyword_group}' not in CORE_RELEVANT_GROUPS or excluded. Skipping.") # Verbose
                    pass # Already logged/printed in contains_keywords if political

    except Exception as e:
        # Log any unexpected error during feed processing
        logging.error(f"Unexpected error processing feed {feed_url}: {e}", exc_info=True) # Log traceback
        print(f"ERROR: Unexpected error processing feed {feed_url}: {e}") # Add print
    return matched_articles_data

def send_email(matched_articles_data): # Takes list of dicts
    today = datetime.now().strftime('%A, %d %B %Y')
    # Ensure SHEET_ID is not None or empty before constructing link
    sheet_link = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}" if SHEET_ID else "#"

    # Define Brand Colors
    mtfa_green = "#006a4e"
    mtfa_blue = "#0d47a1"
    link_color = mtfa_blue
    light_accent_bg = "#e8f5e9"
    divider_color = "#eeeeee"
    body_bg_color = "#f8f9fa"
    container_bg_color = "#ffffff"
    quiz_bg_color = "#eef2f7" # Slightly different background for quiz
    quiz_border_color = "#d0d9e2"

    # --- Select Random Quiz ---
    quiz_html = ""
    quiz_answer_text = "N/A"
    if mtfa_quiz_data:
        try: # Add try-except for robustness in case mtfa_quiz_data is empty or malformed
            quiz_item = random.choice(mtfa_quiz_data)
            quiz_question = quiz_item.get("question", "Quiz question missing.") # Use .get for safer dict access
            quiz_options = quiz_item.get("options", [])
            quiz_options_html = "<br>".join(quiz_options) if quiz_options else "Options missing."
            quiz_answer_text = quiz_item.get("answer", "Answer missing.") # Store answer for footer

            quiz_html = f"""
            <div style="background-color: {quiz_bg_color}; border: 1px solid {quiz_border_color}; padding: 15px 20px; margin-top: 30px; margin-bottom: 30px; border-radius: 6px;">
              <h3 style="color: {mtfa_green}; margin-top: 0; margin-bottom: 12px; font-size: 16px;">🤔 MTFA Quick Quiz!</h3>
              <p style="font-size: 14px; color: #333; line-height: 1.6; margin-bottom: 10px;">{quiz_question}</p>
              <p style="font-size: 14px; color: #555; line-height: 1.6;">{quiz_options_html}</p>
              <p style="font-size: 12px; color: #777; margin-top: 10px;"><i>(Answer revealed in the footer!)</i></p>
            </div>
            """
        except (IndexError, KeyError, TypeError) as quiz_err: # Catch specific potential errors
            logging.warning(f"Could not select/format quiz item: {quiz_err}")
            quiz_html = "" # Ensure it's empty on error
            quiz_answer_text = "Error loading quiz"
    else:
        logging.warning("mtfa_quiz_data list is empty. No quiz will be added.")


    # --- Categorize Articles ---
    # --- START OF AMENDMENT: Add new category for Other Social Sector news ---
    categorized_articles = { "MTFA": [], "Competitor": [], "OtherSocialSector": [], "General": [] }
    # Define groups clearly using sets for efficient lookup
    mtfa_groups = {"MTFA_Main", "Darul_Ihsan_Orphanage", "Ihsan_Casket", "Ihsan_Kidney_Care",
                   "MTFA_Financial_Aid", "MTFA_Education_Support", "MTFA_Childcare_Service"}
    competitor_groups = {"Competitor_Kidney_NKF", "Competitor_Kidney_KDF", "Competitor_Kidney_Other",
                         "Competitor_MuslimAid_RLAF", "Competitor_MuslimAid_AMP",
                         "Competitor_ChildrenHome_CSLMCH", "Competitor_ChildrenHome_Melrose",
                         "Competitor_IslamicBurial", "Competitor_FreeTuition", "Competitor_Childcare"}
    # Define the new group for categorization
    other_social_sector_groups = {"SocialSector_Advocacy_Support"}
    # --- END OF AMENDMENT ---

    # Sort articles into categories
    for article in matched_articles_data:
        group = article.get('keyword_group') # Use .get for safety
        if group in mtfa_groups: categorized_articles["MTFA"].append(article)
        elif group in competitor_groups: categorized_articles["Competitor"].append(article)
        # --- START OF AMENDMENT: Categorize into OtherSocialSector ---
        elif group in other_social_sector_groups: categorized_articles["OtherSocialSector"].append(article)
        # --- END OF AMENDMENT ---
        # Only add to General if it's in CORE_RELEVANT_GROUPS and not already categorized
        elif group in CORE_RELEVANT_GROUPS: categorized_articles["General"].append(article)
        # Articles not matching any of these will be ignored

    # Sort articles within each category by date (newest first)
    for category in categorized_articles:
        categorized_articles[category].sort(key=lambda x: x.get('published_date', datetime.min), reverse=True) # Add default for sorting robustness

    # --- Build HTML Body Content ---
    body_content = ""
    # Use the flat list of all keywords for highlighting
    all_keywords_flat = keywords # Already defined globally

    # Helper function to create HTML for a category section
    def create_category_html(title, articles):
        if not articles: return "" # Skip section if no articles
        section_html = f'<h2 style="color: {mtfa_green}; border-bottom: 2px solid {divider_color}; padding-bottom: 8px; margin-top: 30px; margin-bottom: 20px; font-size: 20px;">{title}</h2>'
        article_blocks = ""
        for article_data in articles:
            # Highlight keywords in the summary
            # Use .get for safer access to dictionary keys
            summary_text = article_data.get('summary', 'Summary not available.')
            headline_text = article_data.get('headline', 'No Headline')
            link_url = article_data.get('link', '#')
            published_dt = article_data.get('published_date')
            keyword_group_text = article_data.get('keyword_group', 'N/A')
            matched_keyword_text = article_data.get('matched_keyword', 'N/A')

            highlighted_summary = highlight_keywords(summary_text, all_keywords_flat)
            # Style for the link button
            link_button_style = f"display: inline-block; padding: 6px 14px; background-color: {light_accent_bg}; color: {mtfa_green}; text-decoration: none; border-radius: 4px; font-size: 13px; font-weight: bold; margin-top: 10px; border: 1px solid {mtfa_green};"
            # Format each article block using f-string for readability
            article_blocks += f"""
            <div style="margin-bottom: 30px; padding-bottom: 20px; border-bottom: 1px solid {divider_color};">
              <h3 style="color: #212529; margin-bottom: 10px; font-size: 17px; font-weight: 600;">{headline_text}</h3>
              <p style="font-size: 15px; color: #343a40; line-height: 1.65; margin-bottom: 10px;"><strong>Summary:</strong> {highlighted_summary}</p>
              <a href="{link_url}" target="_blank" style="{link_button_style}">🔗 Read Full Article</a>
              <p style="font-size: 12px; color: #6c757d; margin-top: 12px;">
                  Published: {published_dt.strftime('%d %b %Y, %H:%M') if published_dt else 'N/A'} |
                  🔖 Group: {keyword_group_text} |
                  🔍 Keyword: {matched_keyword_text}
              </p>
            </div>
            """
        return section_html + article_blocks

    # Create HTML sections for each category using the helper function
    body_content += create_category_html("MTFA & Subsidiary Updates", categorized_articles["MTFA"])
    body_content += create_category_html("Competitor & Peer News", categorized_articles["Competitor"]) # Renamed for clarity
    # --- START OF AMENDMENT: Add new section to email body ---
    body_content += create_category_html("Other Social Sector News", categorized_articles["OtherSocialSector"])
    # --- END OF AMENDMENT ---
    body_content += create_category_html("General Topics", categorized_articles["General"])

    # Handle case where no relevant articles were found *after categorization*
    # Check if ALL categorized lists are empty
    if not any(categorized_articles.values()):
        # Prepare the 'no news' message
        no_news_message = "<p style='text-align: center; font-style: italic; color: #6c757d; padding-top: 20px;'>No relevant news items found matching core criteria in today's crawl.</p>"
        logging.info("No relevant articles found to include in email body after categorization.")
        print("INFO: No relevant articles found to include in email body after categorization.") # Add print
        # Add quiz html first, then the 'no news' message
        body_content = quiz_html + no_news_message
    else:
        # Add intro text and quiz if articles were found
        intro_text = f"""
        <p style="font-size: 16px; color: #343a40; text-align: center; margin-bottom: 30px;">
            Key news items related to MTFA, competitors, and relevant topics gathered for {today}.
        </p>
        """
        # Place quiz after intro, then the generated article content
        body_content = intro_text + quiz_html + body_content

    # --- Construct the full email body ---
    # Using f-string for easier embedding of variables and ensure DOCTYPE
    body = f"""<!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>MTFA Daily Media Report</title> <style>
            body, h1, h2, h3, p {{ margin: 0; padding: 0; font-family: Verdana, Geneva, Tahoma, sans-serif; }}
            body {{ background-color: {body_bg_color}; -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }} /* Added text size adjust */
            .email-container {{ max-width: 750px; margin: 20px auto; background-color: {container_bg_color}; border-radius: 8px; padding: 30px 40px; box-shadow: 0 2px 10px rgba(0,0,0,0.08); border-top: 5px solid {mtfa_green}; }}
            a {{ color: {link_color}; text-decoration: none;}} /* Ensure default underline is off */
            a:hover {{ text-decoration: underline; }} /* Add underline on hover */
            img {{ max-width: 100%; height: auto; border: 0; }} /* Responsive images, remove border */
        </style>
      </head>
      <body style="padding: 20px; margin: 0; background-color: {body_bg_color};">
        <div class="email-container">
          <img src='cid:MTFA_logo' alt='MTFA Logo' style='display:block; margin: 0 auto 25px auto; max-height:70px; border:0;' /> <h1 style="color: {mtfa_green}; text-align: center; margin-bottom: 30px; font-size: 24px; font-weight: bold;">MTFA Daily Media Report</h1>
          {body_content}
          <hr style="border: none; border-top: 1px solid {divider_color}; margin: 30px 0;" />
          <p style="font-size: 12px; text-align: center; color: #6c757d; line-height: 1.5;"> <strong style='color:{mtfa_green};'>Quiz Answer:</strong> {quiz_answer_text}<br><br>
            Automated report generated by MTFA’s Media Monitor Bot.<br>
            Designed by Ath Thaariq Marthas (MSE-OCE) | Powered by Office of the CEO✨<br>
            <a href="{sheet_link}" target="_blank" style="color: {link_color}; text-decoration: none; font-weight: bold;">📊 View history in Google Sheets</a>
          </p>
        </div>
      </body>
    </html>
    """


    # Email Sending Logic
    sender_email = os.getenv("SENDER_EMAIL", "ath@mtfa.org") # Get from env or default
    email_password = os.getenv("EMAIL_PASSWORD")

    # Main recipient(s) - Ensure it's a list
    to_email = ["abdulqader@mtfa.org"]

    # CC recipients - Ensure it's a list
    cc_emails = [
        "officeofed@mtfa.org",
        "msaifulmtfa@mtfa.org",
        "mardhiyyah@mtfa.org",
        "juliyah@mtfa.org",
        "nishani@mtfa.org", # Corrected typo?
        "farhan.zohri@mtfa.org"
    ]

    # Combine all recipients for logging/checking
    all_recipients_list = to_email + cc_emails # Use a different name to avoid scope issues

    # Check for password presence
    if not email_password:
        logging.error("EMAIL_PASSWORD environment variable not set. Cannot send email.")
        print("ERROR: EMAIL_PASSWORD environment variable not set. Cannot send email.")
        return # Exit function if no password

    # Check if there are any recipients configured
    if not all_recipients_list:
        logging.error("No recipient emails configured (To or Cc). Cannot send email.")
        print("ERROR: No recipient emails configured (To or Cc). Cannot send email.")
        return # Exit function if no recipients

    # Create the email message object
    msg = MIMEMultipart('related') # Use 'related' for embedded images
    msg['From'] = f"MTFA Media Bot <{sender_email}>"
    msg['To'] = ", ".join(to_email) # Format for header
    msg['Cc'] = ", ".join(cc_emails) # Format for header
    msg['Subject'] = f"MTFA Daily Media Report - {today}"
    # Set Message-ID for better tracking if needed (optional)
    # from email.utils import make_msgid
    # msg['Message-ID'] = make_msgid(domain='mtfa.org')

    # Attach HTML body - Ensure encoding is explicitly set
    try:
        html_part = MIMEText(body, _subtype='html', _charset='utf-8')
        msg.attach(html_part)
    except Exception as e:
        logging.error(f"Error encoding or attaching HTML body: {e}")
        print(f"ERROR: Error encoding or attaching HTML body: {e}")
        return # Cannot proceed without body

    # Attach logo image
    try:
        # Ensure this path is correct relative to the script's execution directory in GitHub Actions
        # Using the consistent lowercase filename assumed based on previous fixes
        logo_path = "webcrawl/MTFA_logo.png" # Make sure file is named this in repo
        if os.path.exists(logo_path):
            with open(logo_path, "rb") as img_file:
                logo = MIMEImage(img_file.read())
                # Ensure Content-ID matches the cid: in the HTML img src (use consistent lowercase)
                logo.add_header('Content-ID', '<MTFA_logo>')
                msg.attach(logo)
                logging.info(f"Successfully attached logo from {logo_path}")
                print(f"INFO: Successfully attached logo from {logo_path}") # Add print
        else:
            logging.warning(f"Logo file not found at {logo_path}. Email will be sent without logo.")
            print(f"WARNING: Logo file not found at {logo_path}.") # Add print
    except Exception as e:
        logging.error(f"Failed to attach logo image: {e}", exc_info=True) # Log traceback
        print(f"ERROR: Failed to attach logo image: {e}") # Add print
        # Decide if sending without logo is acceptable, or return
        # return # Uncomment if logo is critical

    # Send the email via SMTP SSL
    try:
        # Use port 465 for SSL connection with Gmail
        smtp_server = smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30) # Added timeout
        # smtp_server.set_debuglevel(1) # Uncomment for verbose SMTP debugging output
        # smtp_server.ehlo() # Optional, for extended hello
        smtp_server.login(sender_email, email_password)
        # send_message handles To/Cc/Bcc based on message headers
        smtp_server.send_message(msg)
        smtp_server.quit()
        logging.info(f"Email sent successfully To: {msg['To']} Cc: {msg['Cc']}")
        print(f"INFO: Email sent successfully To: {msg['To']} Cc: {msg['Cc']}") # Add print
    except smtplib.SMTPAuthenticationError:
        # Specific error for bad username/password (or App Password needed)
        logging.error("SMTP Authentication Error: Check sender email and password/app password.")
        print("ERROR: SMTP Authentication Error: Check sender email and password/app password.") # Add print
    except smtplib.SMTPException as smtp_ex:
        # Catch other potential SMTP errors (connection, sending, etc.)
        logging.error(f"SMTP Error occurred: {smtp_ex}", exc_info=True)
        print(f"ERROR: SMTP Error occurred: {smtp_ex}") # Add print
    except Exception as e:
        # Catch any other unexpected errors during SMTP process
        logging.error(f"Failed to send email via SMTP: {e}", exc_info=True) # Log traceback
        print(f"ERROR: Failed to send email via SMTP: {e}") # Add print


# --- RSS Feed List ---
# Revised list focusing on relevance and known working feeds
# Consider adding Business Times if a reliable feed exists
rss_feeds = [
    # --- Major Singapore News ---
    "https://www.straitstimes.com/news/singapore/rss.xml",
    "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=10416", # CNA Singapore Feed
    "https://www.todayonline.com/feed",
    "https://www.asiaone.com/rss/latest.xml",
    "https://www.tnp.sg/rss.xml", # The New Paper

    # --- Malay Language News ---
    # Google News search might be less reliable than direct feeds if available
    "https://news.google.com/rss/search?q=site:beritaharian.sg", # Google News search for Berita Harian

    # --- Relevant Gov / Statutory Boards ---
    "https://news.google.com/rss/search?q=site:muis.gov.sg", # Google News search for MUIS
    'https://news.google.com/rss/search?q=site:msf.gov.sg+OR+"Ministry+of+Social+and+Family+Development"', # Google News search for MSF

    # Add this to your rss_feeds list
    'https://news.google.com/rss/search?q=site:businesstimes.com.sg+charity+OR+non-profit+OR+philanthropy+OR+"social+impact"',

    # --- Direct MTFA Search ---
    "https://news.google.com/rss/search?q=Muslimin+Trust+Fund+Association+Singapore", # Specific search for MTFA

    # --- Key Competitor/Peer Monitoring (via Google News) ---
    'https://news.google.com/rss/search?q="National+Kidney+Foundation"+NKF+Singapore', # NKF Monitoring
    'https://news.google.com/rss/search?q="Kidney+Dialysis+Foundation"+KDF+Singapore', # KDF Monitoring
    'https://news.google.com/rss/search?q="Rahmatan+Lil+Alamin+Foundation"+RLAF', # RLAF Monitoring
    'https://news.google.com/rss/search?q="Association+of+Muslim+Professionals"+AMP+Singapore', # AMP Monitoring

    # --- START OF AMENDMENT: Added The Online Citizen (via Google News) ---
    'https://news.google.com/rss/search?q=site:theonlinecitizen.com+(HOME+OR+"Humanitarian+Organisation+for+Migration+Economics"+OR+"migrant+workers"+OR+fundraising+OR+donation+OR+charity+OR+non-profit+OR+advocacy+OR+vulnerable)',
    # --- END OF AMENDMENT ---

    # --- Potential Addition: Business Times ---
    # Need to find the correct RSS feed URL for Business Times Singapore Lifestyle/Community section
    # Example placeholder - *Needs verification via search*
    # "https://www.businesstimes.com.sg/rss/lifestyle" # <-- VERIFY THIS URL - REMOVED as specific feed unknown
]


# --- Main Execution Logic ---
if __name__ == "__main__":
    logging.info("--- Script Execution Started ---")
    print("--- Script Execution Started ---") # Clear start marker
    start_time = time.time()

    all_matched_articles_data = []
    for feed_url in rss_feeds:
        # Process feed and get list of data dictionaries
        articles_data = parse_rss_feed(feed_url)
        if articles_data: # Only extend if data was found
            all_matched_articles_data.extend(articles_data)

        # Delay between feeds to be polite to servers
        feed_delay = random.uniform(8, 15) # Random delay between 8-15 seconds
        logging.info(f"Finished processing {feed_url}. Waiting {feed_delay:.2f} seconds...")
        # print(f"INFO: Finished processing {feed_url}. Waiting {feed_delay:.2f} seconds...") # Can be verbose
        time.sleep(feed_delay)

    # --- De-duplication Step ---
    unique_articles_data = []
    seen_headlines = set()
    duplicates_found = 0

    logging.info(f"Collected {len(all_matched_articles_data)} potentially relevant articles. Starting de-duplication...")
    print(f"INFO: Collected {len(all_matched_articles_data)} potentially relevant articles. Starting de-duplication...")

    for article_data in all_matched_articles_data:
        # Normalize headline for comparison (lowercase, strip whitespace)
        # Ensure headline is a string before lowercasing/stripping
        headline_text = article_data.get('headline', '')
        normalized_headline = str(headline_text).lower().strip() if headline_text else ""

        if normalized_headline and normalized_headline not in seen_headlines: # Ensure not empty
            seen_headlines.add(normalized_headline)
            unique_articles_data.append(article_data)
        elif not normalized_headline:
            logging.warning("Encountered article data with empty headline during de-duplication.")
        else:
            # Log duplicates if needed for debugging
            duplicates_found += 1
            # logging.info(f"Skipping duplicate headline: {headline_text}") # Can be verbose

    logging.info(f"De-duplication complete. Found {duplicates_found} duplicates. Keeping {len(unique_articles_data)} unique articles.")
    print(f"INFO: De-duplication complete. Found {duplicates_found} duplicates. Keeping {len(unique_articles_data)} unique articles.")
    # --- End De-duplication Step ---


    # Send email with the DE-DUPLICATED data
    if unique_articles_data:
        logging.info(f"Preparing email with {len(unique_articles_data)} unique relevant articles.")
        print(f"INFO: Preparing email with {len(unique_articles_data)} unique relevant articles.") # Add print
        send_email(unique_articles_data) # Pass the filtered list
    else:
        logging.info("No relevant articles found after de-duplication. Sending notification email.")
        print("INFO: No relevant articles found after de-duplication. Sending notification email.") # Add print
        send_email([]) # Sending empty list triggers the "no items" message

    end_time = time.time()
    logging.info(f"--- Script Execution Finished. Total time: {end_time - start_time:.2f} seconds. ---")
    print(f"--- Script Execution Finished. Total time: {end_time - start_time:.2f} seconds. ---") # Clear end marker
