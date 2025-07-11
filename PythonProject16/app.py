import streamlit as st
import google.generativeai as genai
import PyPDF2
import io
import requests
from bs4 import BeautifulSoup
import datetime
from urllib.parse import quote
import streamlit_authenticator as stauth
from fpdf import FPDF
import yaml
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

def export_to_pdf(content):
    """Exports a string to a PDF file."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    # Replace non-latin characters that FPDF doesn't support
    content = content.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 10, content)
    return pdf.output(dest="S").encode("latin-1")

def run_main_app():
    """The main application logic after successful authentication."""
    # --- API Key Configuration ---
    try:
        GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
        genai.configure(api_key=GEMINI_API_KEY)
    except (FileNotFoundError, KeyError) as e:
        st.error(f"A required API key is missing from secrets: {e}. Please contact the administrator.")
        st.stop()

    # --- Model Selection ---
    model = genai.GenerativeModel('gemini-1.5-flash-latest')

    # --- Initialize Session State ---
    for key in ["messages", "chat_session", "fetched_job_title", "fetched_job_description"]:
        if key not in st.session_state:
            st.session_state[key] = [] if key == "messages" else ""

    # --- Sidebar for Inputs ---
    with st.sidebar:
        st.header("Your Details & Job Info")
        st.markdown("---")
        resume_file = st.file_uploader("1. Upload Resume (PDF/TXT)", type=["pdf", "txt"])
        resume_image = st.file_uploader("Or Upload Resume Image (PNG/JPG)", type=["png", "jpg", "jpeg"])
        
        st.header("Job Details")
        st.markdown("---")
        job_title = st.text_input("Job Title", key="job_title_input")
        job_description = st.text_area("Job Description", key="job_desc_input", height=200)
        
        st.header("Action")
        st.markdown("---")
        action = st.selectbox(
            "What do you need help with?",
            ["Generate Cover Letter", "Tailor Resume for Job", "Prepare for Interview", "Skill Gap Analysis"],
            key="action_select"
        )

        if st.button("✨ Generate Initial Draft", use_container_width=True, type="primary"):
            if (resume_file or resume_image) and job_title and job_description:
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
                    
                    company_name = job_description.splitlines()[0] if job_description.splitlines() else job_title
                    
                    prompts = {
                        "Generate Cover Letter": f"First, analyze the provided resume text and extract the following details: Full Name, Full Address, Phone Number, and Email. If a LinkedIn URL is present, extract it as well. Second, using the extracted details, write a complete and professional cover letter for the job of '{job_title}'. The cover letter MUST start with a professional header formatted exactly like this, using the extracted information:\n[Your Name]\n[Your Address]\n[Your Phone Number] | [Your Email] | [Your LinkedIn Profile URL (if found)]\n\n{datetime.date.today().strftime('%B %d, %Y')}\n\nHiring Manager\n{company_name}\n\nDear Hiring Manager,\n[Continue with the body of the cover letter, tailored to the job description and resume.]\n\n**My Resume:**\n{resume_text}\n\n**Job Description:**\n{job_description}",
                        "Tailor Resume for Job": f"Act as a professional resume editor. Your task is to tailor the following resume to better match the given job description. Output the complete, updated resume text in Markdown format.\n\n**My Original Resume:**\n{resume_text}\n\n**Job Title:**\n{job_title}\n\n**Job Description:**\n{job_description}",
                        "Prepare for Interview": f"Act as an experienced hiring manager. Generate 10 common and insightful interview questions for the '{job_title}' role, based on the provided job description and my resume. For each question, provide a sample answer.\n\n**My Resume:**\n{resume_text}\n\n**Job Description:**\n{job_description}",
                        "Skill Gap Analysis": f"Act as a career advisor. Analyze my resume against the job description. Identify key skills I am missing and list them. Then, suggest specific online courses, certifications, or projects I could undertake to fill these gaps.\n\n**My Resume:**\n{resume_text}\n\n**Job Title:**\n{job_title}\n\n**Job Description:**\n{job_description}"
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
        
        st.markdown("---")
        st.session_state.authenticator.logout('Logout', 'sidebar')

    # --- Main App Interface with Tabs ---
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
        st.header("Find Job Postings Online")
        st.markdown("Enter your desired job title and location to generate direct search links to popular job boards.")
        search_keywords = st.text_input("Keywords (e.g., Python Developer)")
        search_location = st.text_input("Location (e.g., Toronto, ON)")
        
        if st.button("Generate Job Search Links"):
            if search_keywords:
                st.markdown("---")
                st.subheader("Your Custom Job Search Links")
                encoded_keywords = quote(search_keywords)
                encoded_location = quote(search_location)
                st.markdown(f"### [Search on Indeed](https://www.indeed.com/jobs?q={encoded_keywords}&l={encoded_location})")
                st.markdown(f"### [Search on LinkedIn](https://www.linkedin.com/jobs/search/?keywords={encoded_keywords}&location={encoded_location})")
                st.markdown(f"### [Search on Google Jobs](https://www.google.com/search?q={encoded_keywords}+jobs+in+{encoded_location}&ibp=htl;jobs)")
            else:
                st.error("Please enter search keywords to generate links.")

# --- Authentication Setup ---
# For production, move this config to a .streamlit/config.yaml file
# and add the file to your .gitignore
config = {
    'credentials': {
        'usernames': {
            'user1': {
                'email': 'user1@example.com',
                'name': 'User One',
                # To generate a new hashed password, run:
                # import streamlit_authenticator as stauth
                # print(stauth.Hasher(['your_password']).generate())
                'password': '$2b$12$EixZaY93b01Ld9p4p4p4p.q9uFQUdD2yI/5TjK.ZtO2w3T2b9QjS' # Hashed "pass123"
            },
            'user2': {
                'email': 'user2@example.com',
                'name': 'User Two',
                'password': '$2b$12$EixZaY93b01Ld9p4p4p4p.q9uFQUdD2yI/5TjK.ZtO2w3T2b9QjS' # Hashed "pass123"
            }
        }
    },
    'cookie': {'expiry_days': 30, 'key': 'some_random_signature_key', 'name': 'some_cookie_name'},
    'preauthorized': {'emails': ['preauth@example.com']}
}

authenticator = stauth.Authenticate(
    config,
    cookie_name='job_helper_cookie',
    key='job_helper_key',
    cookie_expiry_days=30,
)
st.session_state.authenticator = authenticator

# --- Login Page ---
name, authentication_status, username = authenticator.login('main')

if authentication_status is False:
    st.error('Username/password is incorrect')
elif authentication_status is None:
    st.warning('Please enter your username and password')
elif authentication_status:
    run_main_app()
