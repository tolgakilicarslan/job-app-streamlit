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

# --- Page Configuration ---
st.set_page_config(layout="wide", page_title="AI Job Application Helper")

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
}
.job-title {
    font-weight: 600;
    font-size: 1.1rem;
}
.company-name {
    font-weight: 500;
    color: #333;
}
</style>
""", unsafe_allow_html=True)

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

def fetch_job_details_from_url(url, model):
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
        extract_response = model.generate_content(extract_prompt)
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

def export_to_pdf(content):
    """Exports a string to a PDF file."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    content = content.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 10, content)
    return pdf.output(dest="S").encode("latin-1")

def run_main_app():
    """The main application logic after successful authentication."""
    try:
        GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
        genai.configure(api_key=GEMINI_API_KEY)
    except (FileNotFoundError, KeyError) as e:
        st.error(f"A required API key is missing from secrets: {e}. Please contact the administrator.")
        st.stop()

    model = genai.GenerativeModel('gemini-1.5-flash-latest')

    for key in ["messages", "chat_session", "job_title_input", "job_desc_input", "mock_jobs"]:
        if key not in st.session_state:
            st.session_state[key] = [] if key in ["messages", "mock_jobs"] else ""

    with st.sidebar:
        st.header("Your Details & Job Info")
        st.markdown("---")
        resume_file = st.file_uploader("1. Upload Resume (PDF/TXT)", type=["pdf", "txt"])
        resume_image = st.file_uploader("Or Upload Resume Image (PNG/JPG)", type=["png", "jpg", "jpeg"])
        
        st.header("Job Details")
        st.markdown("---")
        job_url = st.text_input("Fetch from Job Posting URL (optional)")
        if st.button("Fetch from URL") and job_url:
            with st.spinner("Fetching and extracting job details..."):
                title, desc = fetch_job_details_from_url(job_url, model)
                if title and desc:
                    st.session_state.job_title_input = title
                    st.session_state.job_desc_input = desc
                    st.success("Job details fetched!")
                else:
                    st.error("Could not extract details. Please paste them manually.")
        
        st.text_input("Job Title", key="job_title_input")
        st.text_area("Job Description", key="job_desc_input", height=200)
        
        st.header("Action")
        st.markdown("---")
        action = st.selectbox(
            "What do you need help with?",
            ["Generate Cover Letter", "Tailor Resume for Job", "Prepare for Interview", "Skill Gap Analysis"],
            key="action_select"
        )

        if st.button("✨ Generate Initial Draft", use_container_width=True, type="primary"):
            if (resume_file or resume_image) and st.session_state.job_title_input and st.session_state.job_desc_input:
                resume_text = ""
                with st.spinner("Reading resume..."):
                    if resume_image:
                        img = Image.open(resume_image)
                        response = model.generate_content(["Extract all text from this resume image.", img])
                        resume_text = response.text
                    elif resume_file:
                        resume_text = read_pdf(resume_file) if resume_file.name.endswith(".pdf") else resume_file.read().decode("utf-8")

                if resume_text:
                    st.session_state.chat_session = model.start_chat(history=[])
                    st.session_state.messages = []
                    
                    company_name = st.session_state.job_desc_input.splitlines()[0] if st.session_state.job_desc_input.splitlines() else st.session_state.job_title_input
                    
                    prompts = {
                        "Generate Cover Letter": f"First, analyze the provided resume text and extract the following details: Full Name, Full Address, Phone Number, and Email. If a LinkedIn URL is present, extract it as well. Second, using the extracted details, write a complete and professional cover letter for the job of '{st.session_state.job_title_input}'. The cover letter MUST start with a professional header formatted exactly like this, using the extracted information:\n[Your Name]\n[Your Address]\n[Your Phone Number] | [Your Email] | [Your LinkedIn Profile URL (if found)]\n\n{datetime.date.today().strftime('%B %d, %Y')}\n\nHiring Manager\n{company_name}\n\nDear Hiring Manager,\n[Continue with the body of the cover letter, tailored to the job description and resume.]\n\n**My Resume:**\n{resume_text}\n\n**Job Description:**\n{st.session_state.job_desc_input}",
                        "Tailor Resume for Job": f"Act as a professional resume editor. Your task is to tailor the following resume to better match the given job description. Output the complete, updated resume text in Markdown format.\n\n**My Original Resume:**\n{resume_text}\n\n**Job Title:**\n{st.session_state.job_title_input}\n\n**Job Description:**\n{st.session_state.job_desc_input}",
                        "Prepare for Interview": f"Act as an experienced hiring manager. Generate 10 common and insightful interview questions for the '{st.session_state.job_title_input}' role, based on the provided job description and my resume. For each question, provide a sample answer.\n\n**My Resume:**\n{resume_text}\n\n**Job Description:**\n{st.session_state.job_desc_input}",
                        "Skill Gap Analysis": f"Act as a career advisor. Analyze my resume against the job description. Identify key skills I am missing and list them. Then, suggest specific online courses, certifications, or projects I could undertake to fill these gaps.\n\n**My Resume:**\n{resume_text}\n\n**Job Title:**\n{st.session_state.job_title_input}\n\n**Job Description:**\n{st.session_state.job_desc_input}"
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
        st.header("Simulated Job Search")
        st.markdown("Find mock job postings to practice generating application materials.")
        search_keywords = st.text_input("Keywords (e.g., Software Engineer)")
        search_location = st.text_input("Location (e.g., Toronto, ON)")
        
        if st.button("Search for Jobs"):
            if search_keywords:
                with st.spinner("Simulating job search..."):
                    st.session_state.mock_jobs = [
                        {"title": f"Senior {search_keywords}", "company": "Innovatech Solutions", "location": search_location, "desc": f"We are seeking a seasoned {search_keywords} with over 5 years of experience to lead our core product development. You will be responsible for mentoring junior developers and driving technical architecture."},
                        {"title": f"{search_keywords}", "company": "Data Systems Co.", "location": search_location, "desc": f"Join our dynamic team as a {search_keywords}. You will work on exciting new projects using cutting-edge technology. A strong understanding of database management is required."},
                        {"title": f"Junior {search_keywords}", "company": "NextGen Startups", "location": search_location, "desc": f"An excellent opportunity for a recent graduate or early-career {search_keywords}. You will learn from senior engineers and contribute to a fast-paced, agile environment."},
                        {"title": f"Lead {search_keywords} (Remote)", "company": "Global Tech LLC", "location": "Remote", "desc": f"This is a fully remote role for a Lead {search_keywords}. You will manage a distributed team and oversee the entire software development lifecycle for our flagship product."}
                    ]
            else:
                st.error("Please enter search keywords to simulate a search.")

        if st.session_state.mock_jobs:
            st.markdown("---")
            st.subheader("Simulated Job Postings")
            for i, job in enumerate(st.session_state.mock_jobs):
                with st.container():
                    st.markdown(f"<div class='job-card'>", unsafe_allow_html=True)
                    st.markdown(f"<div class='job-title'>{job['title']}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='company-name'>{job['company']} - {job['location']}</div>", unsafe_allow_html=True)
                    st.markdown(f"<p>{job['desc']}</p>", unsafe_allow_html=True)
                    
                    if st.button("Prepare for this Job", key=f"prepare_{i}"):
                        st.session_state.job_title_input = job['title']
                        st.session_state.job_desc_input = job['desc']
                        st.success(f"Job details for '{job['title']}' loaded into the sidebar!")
                    
                    st.markdown(f"</div>", unsafe_allow_html=True)

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
