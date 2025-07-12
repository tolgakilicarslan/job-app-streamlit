import streamlit as st
import google.generativeai as genai
import PyPDF2
import io
import requests
from bs4 import BeautifulSoup
import datetime
from urllib.parse import quote
from fpdf import FPDF
from PIL import Image
import re
import gspread
from google.oauth2.service_account import Credentials
import json

# --- Page Configuration ---
st.set_page_config(layout="wide", page_title="AI Job Application Helper")

# --- Helper Functions ---
@st.cache_data
def read_pdf(file):
    """Reads and extracts text from an uploaded PDF file."""
    try:
        pdf_reader = PyPDF2.PdfReader(file)
        text = "".join(page.extract_text() for page in pdf_reader.pages)
        return text
    except Exception as e:
        st.error(f"Error reading PDF file: {e}")
        return None

@st.cache_data
def fetch_job_details_from_url(_model, url):
    """Fetches and extracts job title and description from a URL using Gemini."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        page_content = soup.get_text(separator=' ', strip=True)[:25000]

        extract_prompt = f"""
        Analyze the following text from a webpage and extract the job title and the full job description.
        Provide the output in this exact format, with no extra text or explanations:
        
        Job Title: [The extracted job title]
        Job Description: [The full, extracted job description]

        Webpage Text:
        {page_content}
        """
        extract_response = _model.generate_content(extract_prompt)
        text = extract_response.text.strip()
        
        lines = text.split('\n')
        job_title = ""
        job_description_lines = []
        
        if lines and lines[0].startswith("Job Title:"):
            job_title = lines[0].replace("Job Title:", "").strip()
        
        desc_started = False
        for line in lines[1:]:
            if line.startswith("Job Description:"):
                job_description_lines.append(line.replace("Job Description:", "").strip())
                desc_started = True
            elif desc_started:
                job_description_lines.append(line.strip())
        
        job_description = '\n'.join(job_description_lines)
        return job_title, job_description
    except Exception as e:
        st.error(f"Error fetching or parsing URL: {e}")
        return "", ""

def search_jobs_api(keywords, location, api_key, page=1, required_skills="", remote_only=False, date_posted="all", country=""):
    """Searches for jobs using the JSearch API with pagination and skill filtering."""
    full_location = ""
    if location:
        full_location = location
    if country != "Any":
        if full_location:
            full_location += ", "
        full_location += country
    
    query = keywords
    if full_location:
        query += f" in {full_location}"
    if required_skills:
        query += f" with skills in {required_skills}"
        
    url = "https://jsearch.p.rapidapi.com/search"
    querystring = {"query": query, "page": str(page), "num_pages": "1", "date_posted": date_posted}
    if remote_only:
        querystring["remote_jobs_only"] = "true"
        
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
    }
    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=20)
        response.raise_for_status()
        return response.json() 
    except requests.exceptions.RequestException as e:
        st.error(f"API request failed: {e}")
        return None

def export_to_pdf(content):
    """Exports a string to a PDF file."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    content = content.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 10, content)
    return pdf.output(dest="S").encode("latin-1")

def format_salary(job):
    """Formats the salary range from a job dictionary."""
    min_salary = job.get('job_min_salary')
    max_salary = job.get('job_max_salary')
    period_value = job.get('job_salary_period')
    
    period = period_value.lower() if isinstance(period_value, str) else ''

    if not min_salary and not max_salary:
        return None
    
    if period:
        period = f" a {period.rstrip('ly')}" if period.endswith('ly') else f" an {period}"
    
    if min_salary and max_salary:
        return f"${min_salary:,.0f} - ${max_salary:,.0f}{period}"
    elif max_salary:
        return f"Up to ${max_salary:,.0f}{period}"
    elif min_salary:
        return f"From ${min_salary:,.0f}{period}"
    return None

@st.cache_resource
def get_gspread_client():
    """Connects to Google Sheets using credentials from Streamlit secrets."""
    try:
        creds_info = st.secrets["gcp_service_account"]
        if isinstance(creds_info, str):
            creds_info = json.loads(creds_info)
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"Failed to connect to Google Sheets: {e}")
        st.info("Please ensure your `gcp_service_account` secret in Streamlit Cloud is either a valid TOML section with key-value pairs or a valid JSON string, and the service account has been shared with your Google Sheet with 'Editor' permissions.")
        return None

@st.cache_data(ttl=600) # Cache for 10 minutes
def get_applied_job_ids(_client, sheet_url):
    """Fetches the list of already applied job IDs from the Google Sheet."""
    if not _client:
        return set()
    try:
        sheet = _client.open_by_url(sheet_url).worksheet("Jobs")
        return set(sheet.col_values(1))
    except Exception as e:
        st.error(f"Could not read from Google Sheet: {e}")
        return set()

def log_applied_job(client, sheet_url, job_data):
    """Appends a new row with the applied job's details to the Google Sheet."""
    if not client:
        return False
    try:
        sheet = client.open_by_url(sheet_url).worksheet("Jobs")
        header = ["Job ID", "Date Applied", "Company", "Job Title", "Location", "Salary", "Source", "Link"]
        
        # Check if sheet is empty or header is incorrect
        if not sheet.row_values(1) or sheet.row_values(1) != header:
            sheet.update('A1', [header])

        row_to_insert = [
            job_data.get("job_id", ""),
            datetime.date.today().isoformat(),
            job_data.get("employer_name", ""),
            job_data.get("job_title", ""),
            job_data.get("job_city", ""),
            format_salary(job_data) or "N/A",
            job_data.get("job_publisher", ""),
            job_data.get("job_apply_link", "")
        ]
        sheet.append_row(row_to_insert)
        return True
    except Exception as e:
        st.error(f"Failed to log job to Google Sheet: {e}")
        return False

# --- Custom CSS for Fonts and Styling ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="st-"] {
    font-family: 'Inter', sans-serif;
}
.stApp { background-color: #f9fafb; }
h1, h2, h3 { color: #1f2937; }
.stButton > button {
    background-color: #3b82f6;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 10px 24px;
    transition: background-color 0.2s;
}
.stButton > button:hover {
    background-color: #2563eb;
}
.job-card {
    border: 1px solid #e0e0e0;
    border-radius: 10px;
    padding: 15px;
    margin-bottom: 15px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    display: flex;
    flex-direction: column;
}
.job-header {
    display: flex;
    align-items: center;
    margin-bottom: 10px;
}
.job-logo {
    width: 50px;
    height: 50px;
    margin-right: 15px;
    border-radius: 5px;
    object-fit: contain;
    background-color: #eee; /* Placeholder background */
}
.job-title-container {
    flex-grow: 1;
}
.job-title {
    font-weight: 600;
    font-size: 1.1rem;
}
.company-name {
    font-weight: 500;
    color: #333;
}
.job-details {
    font-size: 0.9rem;
    color: #555;
    margin-top: 10px;
    display: flex;
    flex-wrap: wrap;
    gap: 15px;
}
.match-rate {
    font-weight: bold;
    color: #10B981;
}
</style>
""", unsafe_allow_html=True)

def run_main_app():
    """The main application logic after successful authentication."""
    try:
        GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
        JSEARCH_API_KEY = st.secrets["JSEARCH_API_KEY"]
        G_SHEET_URL = st.secrets["g_sheet_url"]
        genai.configure(api_key=GEMINI_API_KEY)
    except (FileNotFoundError, KeyError) as e:
        st.error(f"A required key is missing from secrets: {e}. Please contact the administrator.")
        st.stop()

    model = genai.GenerativeModel('gemini-1.5-pro-latest')
    gs_client = get_gspread_client()

    PLATFORM_LOGOS = {
        "linkedin": "https://placehold.co/100x100/0A66C2/FFFFFF?text=IN",
        "indeed": "https://placehold.co/100x100/2164F3/FFFFFF?text=ID",
        "google": "https://placehold.co/100x100/4285F4/FFFFFF?text=G",
        "ziprecruiter": "https://placehold.co/100x100/2557A7/FFFFFF?text=ZR",
        "glassdoor": "https://placehold.co/100x100/0CAA41/FFFFFF?text=GD"
    }
    MAPLE_LEAF_LOGO = 'https://placehold.co/100x100/FF0000/FFFFFF?text=🍁'

    # Initialize session state variables
    for key in ["messages", "chat_session", "job_title", "job_description", "live_jobs", "current_page", "resume_text", "search_params", "total_jobs"]:
        if key not in st.session_state:
            st.session_state[key] = [] if key in ["messages", "live_jobs"] else 1 if key == "current_page" else {} if key == "search_params" else 0 if key == "total_jobs" else ""

    with st.sidebar:
        st.header("Your Details & Job Info")
        st.markdown("---")
        resume_file = st.file_uploader("1. Upload Resume (PDF/TXT)", type=["pdf", "txt"])
        resume_image = st.file_uploader("Or Upload Resume Image (PNG/JPG)", type=["png", "jpg", "jpeg"])

        if 'resume_text' not in st.session_state:
            st.session_state.resume_text = ""
            
        if resume_file and not st.session_state.resume_text:
            st.session_state.resume_text = read_pdf(resume_file) if resume_file.name.endswith(".pdf") else resume_file.read().decode("utf-8")
        elif resume_image and not st.session_state.resume_text:
            img = Image.open(resume_image)
            with st.spinner("Reading resume image..."):
                response = model.generate_content(["Extract all text from this resume image.", img])
                st.session_state.resume_text = response.text
        
        st.header("Job Details")
        st.markdown("---")
        
        job_url = st.text_input("Fetch from Job Posting URL (optional)")
        if st.button("Fetch from URL") and job_url:
            with st.spinner("Fetching and extracting job details..."):
                title, desc = fetch_job_details_from_url(model, job_url)
                if title and desc:
                    st.session_state.job_title = title
                    st.session_state.job_description = desc
                    st.success("Job details fetched!")
                    st.rerun() 
                else:
                    st.error("Could not extract details. Please paste them manually.")

        st.session_state.job_title = st.text_input("Job Title", value=st.session_state.job_title)
        st.session_state.job_description = st.text_area("Job Description", value=st.session_state.job_description, height=200)
        
        st.header("Action")
        st.markdown("---")
        action = st.selectbox(
            "What do you need help with?",
            ["Generate Cover Letter", "Tailor Resume for Job", "Prepare for Interview", "Skill Gap Analysis"],
            key="action_select"
        )

        if st.button("✨ Generate Initial Draft", use_container_width=True, type="primary"):
            if st.session_state.resume_text and st.session_state.job_title and st.session_state.job_description:
                st.session_state.chat_session = model.start_chat(history=[])
                st.session_state.messages = []
                
                company_name = st.session_state.job_description.splitlines()[0] if st.session_state.job_description.splitlines() else st.session_state.job_title
                
                prompts = {
                    "Generate Cover Letter": f"First, analyze the provided resume text and extract the following details: Full Name, Full Address, Phone Number, and Email. If a LinkedIn URL is present, extract it as well. Second, using the extracted details, write a complete and professional cover letter for the job of '{st.session_state.job_title}'. The cover letter MUST start with a professional header formatted exactly like this, using the extracted information:\n[Your Name]\n[Your Address]\n[Your Phone Number] | [Your Email] | [Your LinkedIn Profile URL (if found)]\n\n{datetime.date.today().strftime('%B %d, %Y')}\n\nHiring Manager\n{company_name}\n\nDear Hiring Manager,\n[Continue with the body of the cover letter, tailored to the job description and resume.]\n\n**My Resume:**\n{st.session_state.resume_text}\n\n**Job Description:**\n{st.session_state.job_description}",
                    "Tailor Resume for Job": f"Act as a professional resume editor. Your task is to tailor the following resume to better match the given job description. Output the complete, updated resume text in Markdown format.\n\n**My Original Resume:**\n{st.session_state.resume_text}\n\n**Job Title:**\n{st.session_state.job_title}\n\n**Job Description:**\n{st.session_state.job_description}",
                    "Prepare for Interview": f"Act as an experienced hiring manager. Generate 10 common and insightful interview questions for the '{st.session_state.job_title}' role, based on the provided job description and my resume. For each question, provide a sample answer.\n\n**My Resume:**\n{st.session_state.resume_text}\n\n**Job Description:**\n{st.session_state.job_description}",
                    "Skill Gap Analysis": f"Act as a career advisor. Analyze my resume against the job description. Identify key skills I am missing and list them. Then, suggest specific online courses, certifications, or projects I could undertake to fill these gaps.\n\n**My Resume:**\n{st.session_state.resume_text}\n\n**Job Title:**\n{st.session_state.job_title}\n\n**Job Description:**\n{st.session_state.job_description}"
                }
                prompt = prompts[action]

                with st.spinner("🤖 Gemini is generating the first draft..."):
                    try:
                        response = st.session_state.chat_session.send_message(prompt)
                        st.session_state.messages.append({"role": "assistant", "content": response.text})
                        st.success("Draft generated!")
                    except Exception as e:
                        st.error(f"An error occurred with the Gemini API: {e}")
            else:
                st.error("Please provide a resume, job title, and description.")

    st.title("AI Job Application Helper")
    
    tab1, tab2 = st.tabs(["📄 AI Document Generator", "🔍 Find a Job"])

    with tab1:
        st.header("Refine Your Document")
        if not st.session_state.chat_session:
            st.info("Please fill out the details in the sidebar and click 'Generate Initial Draft' to begin.")
        else:
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            if prompt := st.chat_input("How can I refine this for you?"):
                st.session_state.messages.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)

                with st.chat_message("assistant"):
                    with st.spinner("Thinking..."):
                        try:
                            response = st.session_state.chat_session.send_message(prompt)
                            st.markdown(response.text)
                            st.session_state.messages.append({"role": "assistant", "content": response.text})
                        except Exception as e:
                            st.error(f"An error occurred: {e}")
            
            if st.session_state.messages:
                st.markdown("---")
                col1, col2, col3 = st.columns([1, 1, 1])
                with col1:
                    if st.button("Clear Chat History"):
                        st.session_state.messages = []
                        st.session_state.chat_session = None
                        st.rerun()
                with col2:
                    last_content = st.session_state.messages[-1]["content"]
                    file_name_md = f"{st.session_state.action_select.lower().replace(' ', '_')}_draft.md"
                    st.download_button("Download as MD", data=last_content, file_name=file_name_md)
                with col3:
                    last_content = st.session_state.messages[-1]["content"]
                    file_name_pdf = f"{st.session_state.action_select.lower().replace(' ', '_')}_draft.pdf"
                    pdf_data = export_to_pdf(last_content)
                    st.download_button("Download as PDF", data=pdf_data, file_name=file_name_pdf, mime="application/pdf")

    with tab2:
        st.header("Live Job Search")
        st.markdown("Find real job postings and instantly prepare application materials.")
        
        with st.form("search_form"):
            col1, col2 = st.columns(2)
            with col1:
                search_keywords = st.text_input("Keywords (e.g., Software Engineer)")
                required_skills = st.text_input("Required Skills (comma-separated)", help="e.g., python, pandas, sql")
            with col2:
                search_location = st.text_input("Location (e.g., Toronto, ON)")
                exclude_keywords = st.text_input("Exclude Keywords (comma-separated)", help="e.g., manager, lead, principal")
            
            col3, col4, col5 = st.columns(3)
            with col3:
                remote_only = st.checkbox("Search for remote jobs only")
            with col4:
                date_posted_options = {"All Time": "all", "Past 24 hours": "today", "Past 3 days": "3days", "Past Week": "week", "Past Month": "month"}
                date_posted_selection = st.selectbox("Date Posted", options=list(date_posted_options.keys()))
                date_posted_api_value = date_posted_options[date_posted_selection]
            with col5:
                country_options = ["Any", "US", "CA", "GB", "AU", "IN"]
                country_selection = st.selectbox("Country", options=country_options)

            submitted = st.form_submit_button("Search for Jobs")
            if submitted:
                st.session_state.current_page = 1
                st.session_state.search_params = {
                    "keywords": search_keywords,
                    "location": search_location,
                    "skills": required_skills,
                    "exclude": exclude_keywords,
                    "remote": remote_only,
                    "date_posted": date_posted_api_value,
                    "country": country_selection
                }
                st.session_state.live_jobs = [] 
                st.session_state.total_jobs = 0

        if st.session_state.search_params.get("keywords"):
            with st.spinner(f"Searching for jobs on page {st.session_state.current_page}..."):
                params = st.session_state.search_params
                api_response = search_jobs_api(params["keywords"], params["location"], JSEARCH_API_KEY, st.session_state.current_page, params["skills"], params["remote"], params["date_posted"], params["country"])
                
                if api_response:
                    all_results = api_response.get('data', [])
                    st.session_state.total_jobs = api_response.get('estimated_total_results', 0)
                    
                    applied_ids = get_applied_job_ids(gs_client, G_SHEET_URL)
                    unapplied_results = [job for job in all_results if job.get('job_id') not in applied_ids]

                    if params["exclude"]:
                        excluded = [kw.strip().lower() for kw in params["exclude"].split(',')]
                        filtered_results = []
                        for job in unapplied_results:
                            title = job.get('job_title', '').lower()
                            description = job.get('job_description', '').lower()
                            if not any(kw in title or kw in description for kw in excluded):
                                filtered_results.append(job)
                        st.session_state.live_jobs = filtered_results
                    else:
                        st.session_state.live_jobs = unapplied_results

        if st.session_state.live_jobs:
            st.markdown("---")
            st.subheader(f"Found approximately {st.session_state.total_jobs} jobs. Displaying page {st.session_state.current_page}.")
            for i, job in enumerate(st.session_state.live_jobs):
                with st.container():
                    st.markdown(f"<div class='job-card'>", unsafe_allow_html=True)
                    
                    st.markdown("<div class='job-header'>", unsafe_allow_html=True)
                    
                    logo_url = job.get('employer_logo')
                    if not logo_url:
                        publisher = job.get('job_publisher', '').lower()
                        logo_url = MAPLE_LEAF_LOGO # Default to Maple Leaf
                        for platform, url in PLATFORM_LOGOS.items():
                            if platform in publisher:
                                logo_url = url
                                break
                    
                    st.markdown(f"<img src='{logo_url}' class='job-logo' alt='company logo'>", unsafe_allow_html=True)
                    st.markdown("<div class='job-title-container'>", unsafe_allow_html=True)
                    st.markdown(f"<div class='job-title'>{job.get('job_title', 'N/A')}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='company-name'>{job.get('employer_name', 'N/A')} - {job.get('job_city', 'N/A')}, {job.get('job_country', '')}</div>", unsafe_allow_html=True)
                    st.markdown("</div></div>", unsafe_allow_html=True)

                    details = []
                    
                    if 'match_rate' in job:
                        details.append(f"<span class='match-rate'>✔ {job['match_rate']}% Match</span>")
                    elif st.session_state.resume_text:
                        if st.button("Calculate Match Rate", key=f"match_{i}"):
                            with st.spinner("AI is calculating match rate..."):
                                match_prompt = f"On a scale of 0 to 100, how well does this resume match the following job description? Provide only the number. Resume: {st.session_state.resume_text}\n\nJob Description: {job.get('job_description', '')}"
                                match_response = model.generate_content(match_prompt)
                                try:
                                    rate = int(re.search(r'\d+', match_response.text).group())
                                    st.session_state.live_jobs[i]['match_rate'] = rate
                                    st.rerun()
                                except (ValueError, AttributeError):
                                    st.session_state.live_jobs[i]['match_rate'] = "N/A"
                                    st.rerun()

                    job_link = job.get('job_apply_link', '#')
                    details.append(f"<strong>Source:</strong> <a href='{job_link}' target='_blank'>{job.get('job_publisher', 'N/A')}</a>")
                    
                    if job.get('job_posted_at_datetime_utc'):
                        post_date = datetime.datetime.fromisoformat(job.get('job_posted_at_datetime_utc').replace('Z', '+00:00'))
                        details.append(f"<strong>Posted:</strong> {post_date.strftime('%b %d, %Y')}")

                    salary = format_salary(job)
                    if salary:
                        details.append(f"<strong>Salary:</strong> {salary}")
                    
                    employment_type = job.get('job_employment_type')
                    if employment_type:
                        details.append(f"<strong>Type:</strong> {employment_type.title()}")
                        
                    st.markdown(f"<div class='job-details'>{' | '.join(details)}</div>", unsafe_allow_html=True)
                    
                    with st.expander("View Job Description and Highlights"):
                        st.markdown(job.get('job_description', 'No description available.'))
                        
                        highlights = job.get('job_highlights')
                        if highlights:
                            st.markdown("---")
                            for section in highlights:
                                title = section.get('title', '')
                                items = section.get('items', [])
                                if title and items:
                                    st.markdown(f"<h5>{title}</h5>", unsafe_allow_html=True)
                                    for item in items:
                                        st.markdown(f"- {item}")

                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Prepare for this Job", key=f"prepare_{i}"):
                            st.session_state.job_title = job.get('job_title', '')
                            st.session_state.job_description = f"{job.get('employer_name', '')}\n\n{job.get('job_description', '')}"
                            st.success(f"Job details for '{job.get('job_title')}' loaded into the sidebar!")
                            st.rerun()
                    with col2:
                        if st.button("Log as Applied", key=f"log_{i}"):
                            if log_applied_job(gs_client, G_SHEET_URL, job):
                                st.success(f"Logged '{job.get('job_title')}' as applied!")
                                st.session_state.live_jobs.pop(i)
                                st.rerun()
                    
                    st.markdown(f"</div>", unsafe_allow_html=True)

            st.markdown("---")
            col1, col2, col3 = st.columns([1, 1, 1])
            with col1:
                if st.session_state.current_page > 1:
                    if st.button("⬅️ Previous Page"):
                        st.session_state.current_page -= 1
                        st.rerun()
            with col2:
                st.write(f"Page {st.session_state.current_page}")
            with col3:
                if len(st.session_state.live_jobs) > 0:
                    if st.button("Next Page ➡️"):
                        st.session_state.current_page += 1
                        st.rerun()

def check_password():
    """Returns `True` if the user had the correct password."""
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    if st.session_state.password_correct:
        return True

    try:
        correct_password = st.secrets["APP_PASSWORD"]
    except (FileNotFoundError, KeyError):
        st.error("APP_PASSWORD secret not found. Please contact the administrator.")
        st.stop()
        
    st.title("Password Required")
    password = st.text_input("Enter password to access the application", type="password")

    if st.button("Login"):
        if password == correct_password:
            st.session_state.password_correct = True
            st.rerun()
        else:
            st.error("The password you entered is incorrect.")
    
    return False

if check_password():
    run_main_app()
