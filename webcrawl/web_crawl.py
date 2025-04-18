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
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

# Load environment variables from creds.env
load_dotenv("creds.env")

# Set up logging
logging.basicConfig(filename="rss_feed.log", level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")

# Load OpenAI API key
# Ensure OPENAI_API_KEY is set in your creds.env file
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Setup Google Sheets API
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = os.getenv("SHEET_ID")  # Your sheet ID in creds.env
# Ensure credentials2.json path is correct and SHEET_ID is set in creds.env
try:
    creds = Credentials.from_service_account_file("credentials2.json", scopes=SCOPES)
    gs_client = gspread.authorize(creds)
    sheet = gs_client.open_by_key(SHEET_ID).sheet1
    logging.info("Google Sheets API authorized successfully.")
except Exception as e:
    logging.error(f"Failed to authorize Google Sheets API: {e}")
    # Exit if Sheets cannot be accessed, or handle differently
    exit()

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

    # --- General Topics (Use CORE_RELEVANT_GROUPS to control inclusion) ---
    "General_Beneficiaries": ["beneficiary", "penerima bantuan", "asnaf", "recipient", "low-income", "needy", "underprivileged", "vulnerable"],
    "General_Donations": ["donation", "derma", "sumbangan", "infaq", "wakaf", "infak", "fundraising", "pengumpulan dana", "donate", "menyumbang", "giving.sg"],
    "General_Zakat": ["zakat", "derma zakat", "bayar zakat"],
    "General_ElderlyCare": ["eldercare", "penjagaan warga emas", "rumah orang tua", "old folks home", "needy elderly"],
    "General_SpecialNeeds": ["special needs", "keperluan khas", "OKU", "disability support"],
}

# Flat list of all keywords used for highlighting in the email
keywords = [kw for group in keyword_groups.values() for kw in group]

# *** CUSTOMIZE THIS LIST TO CONTROL WHAT GETS SUMMARIZED ***
# Option A: Include MTFA groups AND specific competitor/peer groups you want summarized.
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
    # "Competitor_ChildrenHome_CSLMCH",# Example: Add if needed
    # "Competitor_FreeTuition",        # Example: Add if needed

    # General Topic Groups (Include carefully if desired)
    "General_Beneficiaries",         # May include broad/unrelated "recipient" news
    "General_Donations",             # May include broad donation news
    "General_Zakat",                 # If general Zakat news is useful
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
        normalized_text = unicodedata.normalize("NFKD", text)
        return ''.join(c for c in normalized_text if not unicodedata.category(c).startswith("Cs"))
    except TypeError:
        logging.warning(f"Could not sanitize non-string input: {type(text)}")
        return ""


def fetch_full_article_content(article_url):
    # Fetches and parses article using newspaper3k with User-Agent
    try:
        config = Config()
        config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
        config.request_timeout = 15
        config.fetch_images = False

        article = Article(article_url, config=config)
        article.download()
        # Check HTTP status code if possible (newspaper hides this sometimes)
        # if article.resp and not (200 <= article.resp.status_code < 300):
        #     logging.warning(f"HTTP Error {article.resp.status_code} for {article_url}")
        #     # Decide if you want to return "" or raise an error here
        article.parse()
        return article.text
    except Exception as e:
        logging.error(f"Failed to fetch/parse article content from {article_url}: {e}")
        return ""


def highlight_keywords(summary, keywords_to_highlight):
    # Highlights keywords in the summary text using HTML span tags
    processed_summary = summary
    for kw in sorted(keywords_to_highlight, key=len, reverse=True):
        try:
            # Use word boundaries (\b) to avoid matching parts of words
            # Escape special regex characters in the keyword
            processed_summary = re.sub(rf"\b({re.escape(kw)})\b", r"<span style='background-color:#fff1a8;'>\1</span>", processed_summary, flags=re.IGNORECASE) # Softer yellow
        except re.error as re_err:
             logging.warning(f"Regex error highlighting keyword '{kw}': {re_err}")
             continue # Skip problematic keyword
    return processed_summary


def generate_gpt_summary(headline, article_content):
    # Generates summary using OpenAI API
    try:
        if not article_content or len(article_content.strip()) < 150: # Min length check
            logging.warning(f"Content too short or missing for '{headline}'. Skipping summary.")
            return "Summary not available."

        content_limit = 3000
        prompt = f"Summarize the following article relevant to a Singaporean charity context in less than 100 words:\n\nTitle: {headline}\n\nContent: {article_content[:content_limit]}"

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.5
        )
        # Check if response is valid
        if response.choices and response.choices[0].message:
             return response.choices[0].message.content.strip()
        else:
             logging.error(f"Invalid response from OpenAI for '{headline}': {response}")
             return "Summary generation failed."

    except Exception as e:
        logging.error(f"Error summarizing '{headline}': {e}")
        # Specific check for OpenAI errors might be useful here too
        return "Summary generation failed."


def contains_keywords(text, headline, headline_weight=2, content_weight=1, threshold=3):
    # Checks if text/headline contain keywords above a threshold score
    # Returns the best matching relevant keyword and group, or None
    score = 0
    best_match_kw = None
    best_match_group = None
    best_match_score = 0

    headline_lower = headline.lower()
    text_lower = text.lower()

    for group, group_keywords in keyword_groups.items():
        for keyword in group_keywords:
            kw_lower = keyword.lower()
            # Use regex findall for more accurate counting of whole words
            try:
                 hl_count = len(re.findall(rf"\b{re.escape(kw_lower)}\b", headline_lower, re.IGNORECASE))
                 txt_count = len(re.findall(rf"\b{re.escape(kw_lower)}\b", text_lower, re.IGNORECASE))
            except re.error:
                 logging.warning(f"Regex error counting keyword '{keyword}'. Skipping count.")
                 hl_count = 0
                 txt_count = 0

            current_score = (hl_count * headline_weight) + (txt_count * content_weight)

            if current_score > 0:
                 score += current_score
                 if group in CORE_RELEVANT_GROUPS and current_score > best_match_score:
                     best_match_score = current_score
                     best_match_kw = keyword
                     best_match_group = group
                 # Optional early exit removed to ensure best match is found if score met
                 # if score >= threshold and group in CORE_RELEVANT_GROUPS: return keyword, group
                 # elif score >= threshold and best_match_kw: return best_match_kw, best_match_group

    # Check after evaluating all keywords
    if score >= threshold and best_match_kw:
         return best_match_kw, best_match_group

    return None, None


def log_to_google_sheets(date_str, headline, summary, keyword, group, link):
    # Appends a row to the configured Google Sheet
    try:
        sheet.append_row([
            str(date_str), str(headline), str(summary),
            str(keyword), str(group), str(link)
        ])
    except Exception as e:
        logging.error(f"Failed to log to Google Sheets: {e}")


def parse_rss_feed(feed_url):
    # Parses a single RSS feed and returns relevant article data
    matched_articles_data = []
    logging.info(f"Processing feed: {feed_url}")
    try:
        # Add a User-Agent to feedparser requests too
        feed_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
        feed = feedparser.parse(feed_url, agent=feed_agent)

        if feed.bozo: # Check if feedparser encountered issues
             logging.warning(f"Feedparser reported issues for {feed_url}: {feed.bozo_exception}")

        date_threshold = datetime.now() - timedelta(days=3)

        for entry in feed.entries:
            published_date = None
            # Try finding a usable date
            if 'published_parsed' in entry and entry.published_parsed:
                try: published_date = datetime(*entry.published_parsed[:6])
                except (ValueError, TypeError): pass
            if not published_date and 'updated_parsed' in entry and entry.updated_parsed: # Fallback
                try: published_date = datetime(*entry.updated_parsed[:6])
                except (ValueError, TypeError): pass

            if not published_date:
                logging.warning(f"No valid date found for entry: {entry.get('title', 'N/A')} in {feed_url}")
                continue

            if published_date >= date_threshold:
                headline = sanitize_unicode(entry.get('title', 'No Title'))
                link = sanitize_unicode(entry.get('link', ''))
                if not link: continue

                rss_summary = sanitize_unicode(entry.get('summary', ''))
                full_article_content = fetch_full_article_content(link) # Already sanitized inside
                content_to_check = sanitize_unicode(full_article_content if len(full_article_content.strip()) > len(rss_summary.strip()) else rss_summary)

                if not content_to_check: continue

                matched_keyword, keyword_group = contains_keywords(content_to_check, headline)

                if matched_keyword and keyword_group in CORE_RELEVANT_GROUPS:
                    logging.info(f"Relevant keyword '{matched_keyword}' (Group: {keyword_group}) found in: {headline}")
                    time.sleep(2) # Delay before OpenAI call
                    summary = generate_gpt_summary(headline, content_to_check)

                    if summary and summary not in ["Summary not available.", "Summary generation failed."]:
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
                        logging.warning(f"Summary generation failed or skipped for: {headline}")
                elif matched_keyword:
                    logging.info(f"Keyword '{matched_keyword}' found in '{headline}' but group '{keyword_group}' not in CORE_RELEVANT_GROUPS. Skipping.")

    except Exception as e:
        logging.error(f"Error processing feed {feed_url}: {e}")
    return matched_articles_data

def send_email(matched_articles_data): # Takes list of dicts
    today = datetime.now().strftime('%A, %d %B %Y')
    sheet_link = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}" # Use variable for link

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
    # Ensure there's data to choose from
    quiz_html = ""
    quiz_answer_text = "N/A"
    if mtfa_quiz_data:
        quiz_item = random.choice(mtfa_quiz_data)
        quiz_question = quiz_item["question"]
        # Format options with line breaks for readability
        quiz_options_html = "<br>".join(quiz_item["options"])
        quiz_answer_text = quiz_item["answer"] # Store answer for footer

        # --- Add Quiz Section HTML ---
        quiz_html = f"""
        <div style="background-color: {quiz_bg_color}; border: 1px solid {quiz_border_color}; padding: 15px 20px; margin-top: 30px; margin-bottom: 30px; border-radius: 6px;">
          <h3 style="color: {mtfa_green}; margin-top: 0; margin-bottom: 12px; font-size: 16px;">🤔 MTFA Quick Quiz!</h3>
          <p style="font-size: 14px; color: #333; line-height: 1.6; margin-bottom: 10px;">{quiz_question}</p>
          <p style="font-size: 14px; color: #555; line-height: 1.6;">{quiz_options_html}</p>
          <p style="font-size: 12px; color: #777; margin-top: 10px;"><i>(Answer revealed in the footer!)</i></p>
        </div>
        """
    else:
        logging.warning("mtfa_quiz_data list is empty. No quiz will be added.")


    # --- Categorize Articles (Same logic as before) ---
    categorized_articles = { "MTFA": [], "Competitor": [], "General": [] }
    mtfa_groups = ["MTFA_Main", "Darul_Ihsan_Orphanage", "Ihsan_Casket", "Ihsan_Kidney_Care",
                   "MTFA_Financial_Aid", "MTFA_Education_Support", "MTFA_Childcare_Service"]
    competitor_groups = ["Competitor_Kidney_NKF", "Competitor_Kidney_KDF", "Competitor_Kidney_Other",
                         "Competitor_MuslimAid_RLAF", "Competitor_MuslimAid_AMP",
                         "Competitor_ChildrenHome_CSLMCH", "Competitor_ChildrenHome_Melrose",
                         "Competitor_IslamicBurial", "Competitor_FreeTuition", "Competitor_Childcare"]
    for article in matched_articles_data:
        group = article['keyword_group']
        if group in mtfa_groups: categorized_articles["MTFA"].append(article)
        elif group in competitor_groups: categorized_articles["Competitor"].append(article)
        else: categorized_articles["General"].append(article)
    for category in categorized_articles:
        categorized_articles[category].sort(key=lambda x: x['published_date'], reverse=True)

    # --- Build HTML Body Content ---
    body_content = ""
    all_keywords_flat = [kw for group in keyword_groups.values() for kw in group]

    def create_category_html(title, articles):
        if not articles: return ""
        section_html = f'<h2 style="color: {mtfa_green}; border-bottom: 2px solid {divider_color}; padding-bottom: 8px; margin-top: 30px; margin-bottom: 20px; font-size: 20px;">{title}</h2>'
        article_blocks = ""
        for article_data in articles:
            highlighted_summary = highlight_keywords(article_data['summary'], all_keywords_flat)
            link_button_style = f"display: inline-block; padding: 6px 14px; background-color: {light_accent_bg}; color: {mtfa_green}; text-decoration: none; border-radius: 4px; font-size: 13px; font-weight: bold; margin-top: 10px; border: 1px solid {mtfa_green};"
            article_blocks += f"""
            <div style="margin-bottom: 30px; padding-bottom: 20px; border-bottom: 1px solid {divider_color};">
              <h3 style="color: #212529; margin-bottom: 10px; font-size: 17px; font-weight: 600;">{article_data['headline']}</h3>
              <p style="font-size: 15px; color: #343a40; line-height: 1.65; margin-bottom: 10px;"><strong>Summary:</strong> {highlighted_summary}</p>
              <a href="{article_data['link']}" target="_blank" style="{link_button_style}">🔗 Read Full Article</a>
              <p style="font-size: 12px; color: #6c757d; margin-top: 12px;">
                  Published: {article_data['published_date'].strftime('%d %b %Y, %H:%M')} |
                  🔖 Group: {article_data['keyword_group']} |
                  🔍 Keyword: {article_data['matched_keyword']}
              </p>
            </div>
            """
        return section_html + article_blocks

    body_content += create_category_html("MTFA & Subsidiary Updates", categorized_articles["MTFA"])
    body_content += create_category_html("Competitor & Sector News", categorized_articles["Competitor"])
    body_content += create_category_html("General Topics", categorized_articles["General"])

    if not body_content:
        # Even if no news, still include quiz? Or just the message? Your choice.
        # Let's include the quiz even if no articles.
        body_content = "<p style='text-align: center; font-style: italic; color: #6c757d; padding-top: 20px;'>No relevant news items found matching core criteria in today's crawl.</p>"
        logging.info("No relevant articles found to include in email body.")
        # Add quiz html here if desired even when no articles
        body_content += quiz_html
    else:
         intro_text = f"""
         <p style="font-size: 16px; color: #343a40; text-align: center; margin-bottom: 30px;">
             Key news items related to MTFA, competitors, and relevant topics gathered for {today}.
         </p>
         """
         # Place quiz after intro, before articles
         body_content = intro_text + quiz_html + body_content

    # --- Construct the full email body ---
    body = f"""
    <html>
      <head>
        <meta charset="UTF-8">
        <style>
            body, h1, h2, h3, p {{ margin: 0; padding: 0; font-family: Verdana, Geneva, Tahoma, sans-serif; }}
            body {{ background-color: {body_bg_color}; }}
            .email-container {{ max-width: 750px; margin: 20px auto; background-color: {container_bg_color}; border-radius: 8px; padding: 30px 40px; box-shadow: 0 2px 10px rgba(0,0,0,0.08); border-top: 5px solid {mtfa_green}; }}
            a {{ color: {link_color}; }}
        </style>
      </head>
      <body style="padding: 20px; margin: 0; background-color: {body_bg_color};">
        <div class="email-container">
          <img src='cid:mtfa_logo' alt='MTFA Logo' style='display:block; margin: 0 auto 25px auto; max-height:70px;' />
          <h1 style="color: {mtfa_green}; text-align: center; margin-bottom: 30px; font-size: 24px; font-weight: bold;">MTFA Daily Media Report</h1>
          {body_content}
          <hr style="border: none; border-top: 1px solid {divider_color}; margin: 30px 0;" />
          <p style="font-size: 12px; text-align: center; color: #6c757d;">
            
            <strong style='color:{mtfa_green};'>Quiz Answer:</strong> {quiz_answer_text}<br><br>
            Automated report generated by MTFA’s Media Monitor Bot.<br>
            Designed by Ath Thaariq Marthas (MSE-OCE) | Powered by GPT-4o ✨<br>
            <a href="{sheet_link}" target="_blank" style="color: {link_color}; text-decoration: none; font-weight: bold;">📊 View history in Google Sheets</a>
          </p>
        </div>
      </body>
    </html>
    """


    # Email Sending Logic
    sender_email = os.getenv("SENDER_EMAIL", "ath@mtfa.org") # Get from env or default
    email_password = os.getenv("EMAIL_PASSWORD")
    
    # Main recipient
    to_email = ["abdulqader@mtfa.org"]

    # CC recipients
    cc_emails = [
        "officeofed@mtfa.org",
        "msaifulmtfa@mtfa.org",
        "mardhiyyah@mtfa.org",
        "juliyah@mtfa.org",
        "sitiumairah@mtfa.org",
        "farhan.zohri@mtfa.org"
    ]

    # Combine all recipients for logging/checking, though send_message uses headers
    all_recipients = to_email + cc_emails

    if not email_password:
        logging.error("EMAIL_PASSWORD environment variable not set. Cannot send email.")
        print("EMAIL_PASSWORD environment variable not set. Cannot send email.")
        return # Exit function if no password

    # Check if there are any recipients at all using the combined list
    if not all_recipients: # <--- CORRECTED LINE
        logging.error("No recipient emails configured (To or Cc). Cannot send email.")
        print("No recipient emails configured (To or Cc). Cannot send email.")
        return # Exit function if no recipients

    msg = MIMEMultipart('related')
    msg['From'] = f"MTFA Media Bot <{sender_email}>"

    msg['To'] = ", ".join(to_email)
    msg['Cc'] = ", ".join(cc_emails)

    msg['Subject'] = f"MTFA Daily Media Report - {today}"
    html_part = MIMEText(body, _subtype='html', _charset='utf-8')
    msg.attach(html_part)

    try:
        logo_path = "mtfa_logo.png"
        if os.path.exists(logo_path):
            with open(logo_path, "rb") as img_file:
                logo = MIMEImage(img_file.read())
                logo.add_header('Content-ID', '<mtfa_logo>')
                msg.attach(logo)
        else: logging.warning(f"Logo file not found at {logo_path}. Email will be sent without logo.")
    except Exception as e: logging.error(f"Failed to attach logo image: {e}")

    try:
        # Ensure you have enabled "less secure app access" for Gmail or use an App Password if 2FA is enabled
        smtp_server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        smtp_server.ehlo()
        smtp_server.login(sender_email, email_password)
        smtp_server.send_message(msg)
        smtp_server.quit()
        logging.info(f"Email sent successfully To: {msg['To']} Cc: {msg['Cc']}")
        print(f"Email sent successfully To: {msg['To']} Cc: {msg['Cc']}")
    except smtplib.SMTPAuthenticationError:
         logging.error("SMTP Authentication Error: Check sender email and password/app password.")
         print("SMTP Authentication Error: Check sender email and password/app password.")
    except Exception as e:
        logging.error(f"Failed to send email via SMTP: {e}")
        print(f"Failed to send email via SMTP: {e}")


# --- RSS Feed List ---
# Revised list focusing on relevance and known working feeds
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

    # --- Charity Sector Specific ---
    "https://news.google.com/rss/search?q=site:giving.sg", # Google News search for Giving.sg

    # --- Direct MTFA Search ---
    "https://news.google.com/rss/search?q=Muslimin+Trust+Fund+Association+Singapore", # Specific search for MTFA

    # --- Key Competitor/Peer Monitoring (via Google News) ---
    'https://news.google.com/rss/search?q="National+Kidney+Foundation"+NKF+Singapore', # NKF Monitoring
    'https://news.google.com/rss/search?q="Kidney+Dialysis+Foundation"+KDF+Singapore', # KDF Monitoring
    'https://news.google.com/rss/search?q="Rahmatan+Lil+Alamin+Foundation"+RLAF', # RLAF Monitoring
    'https://news.google.com/rss/search?q="Association+of+Muslim+Professionals"+AMP+Singapore', # AMP Monitoring
]


# --- Main Execution Logic ---
# --- Main Execution Logic ---
if __name__ == "__main__":
    logging.info("Starting script execution...")
    start_time = time.time()

    all_matched_articles_data = []
    for feed_url in rss_feeds:
        # Process feed and get list of data dictionaries
        articles_data = parse_rss_feed(feed_url)
        if articles_data: # Only extend if data was found
             all_matched_articles_data.extend(articles_data)

        # Delay between feeds
        feed_delay = 15 # Reduced delay
        logging.info(f"Finished processing {feed_url}. Waiting {feed_delay} seconds...")
        time.sleep(feed_delay)

    # --- De-duplication Step ---
    unique_articles_data = []
    seen_headlines = set()
    duplicates_found = 0

    # Sort by date first (optional, ensures we keep the earliest encountered version if desired)
    # all_matched_articles_data.sort(key=lambda x: x['published_date'])

    logging.info(f"Collected {len(all_matched_articles_data)} potentially relevant articles. Starting de-duplication...")

    for article_data in all_matched_articles_data:
        # Normalize headline for comparison (lowercase, strip whitespace)
        normalized_headline = article_data['headline'].lower().strip()

        if normalized_headline not in seen_headlines:
            seen_headlines.add(normalized_headline)
            unique_articles_data.append(article_data)
        else:
            duplicates_found += 1
            logging.info(f"Skipping duplicate headline: {article_data['headline']}")

    logging.info(f"De-duplication complete. Found {duplicates_found} duplicates. Keeping {len(unique_articles_data)} unique articles.")
    # --- End De-duplication Step ---


    # Send email with the DE-DUPLICATED data
    if unique_articles_data:
        logging.info(f"Preparing email with {len(unique_articles_data)} unique relevant articles.")
        send_email(unique_articles_data) # Pass the filtered list
    else:
        logging.info("No relevant articles found after de-duplication. Sending notification email.")
        send_email([]) # Sending empty list triggers the "no items" message

    end_time = time.time()
    logging.info(f"Script finished execution. Total time: {end_time - start_time:.2f} seconds.")
    print(f"Script finished. Total time: {end_time - start_time:.2f} seconds.")