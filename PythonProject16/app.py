import streamlit as st
import google.generativeai as genai
import PyPDF2
import io
import requests
from bs4 import BeautifulSoup
import datetime
from urllib.parse import quote

# --- Page Configuration ---
st.set_page_config(layout="wide", page_title="AI Job Application Helper")

# --- Custom CSS for Fonts and Styling ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="st-"] {
    font-family: 'Inter', sans-serif;
}
.st-emotion-cache-1y4p8pa {
    padding-top: 2rem;
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
.job-details {
    font-size: 0.9rem;
    color: #555;
    margin-top: 10px;
}
</style>
""", unsafe_allow_html=True)

# --- Helper Functions ---
def read_pdf(file):
    """Reads and extracts text from an uploaded PDF file."""
    try:
        pdf_reader = PyPDF2.PdfReader(file)
        text = "".join(page.extract_text() for page in pdf_reader.pages)
        return text
    except Exception as e:
        st.error(f"Error reading PDF file: {e}")
        return None

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
    for key in ["messages", "chat_session", "fetched_job_title", "fetched_job_description", "active_tab"]:
        if key not in st.session_state:
            st.session_state[key] = [] if key == "messages" else ""

    # --- Sidebar for Inputs ---
    with st.sidebar:
        st.header("Your Details & Job Info")
        resume_file = st.file_uploader("1. Upload Resume (TXT or PDF)", type=["txt", "pdf"])
        
        st.header("Job Details")
        st.markdown("Enter details manually, or select a job from the 'Find a Job' tab.")
        
        job_title = st.text_input("Job Title", key="job_title_input", value=st.session_state.fetched_job_title)
        job_description = st.text_area("Job Description", key="job_desc_input", height=200, value=st.session_state.fetched_job_description)
        
        st.header("Action")
        action = st.selectbox(
            "What do you need help with?",
            ["Generate Cover Letter", "Tailor Resume for Job", "Prepare for Interview"],
            key="action_select"
        )

        if st.button("✨ Generate Initial Draft", use_container_width=True, type="primary"):
            if resume_file and job_title and job_description:
                with st.spinner("Reading resume..."):
                    resume_text = read_pdf(resume_file) if resume_file.name.endswith(".pdf") else resume_file.read().decode("utf-8")

                if resume_text:
                    st.session_state.chat_session = model.start_chat(history=[])
                    st.session_state.messages = []
                    
                    # Enhanced prompts
                    company_name = job_description.splitlines()[0] if job_description.splitlines() else job_title
                    
                    prompts = {
                        "Generate Cover Letter": f"""
                        First, analyze the provided resume text and extract the following details: Full Name, Full Address, Phone Number, and Email.
                        If a LinkedIn URL is present, extract it as well.

                        Second, using the extracted details, write a complete and professional cover letter for the job of '{job_title}'.
                        The cover letter MUST start with a professional header formatted exactly like this, using the extracted information:
                        [Your Name]
                        [Your Address]
                        [Your Phone Number] | [Your Email] | [Your LinkedIn Profile URL (if found)]

                        {datetime.date.today().strftime('%B %d, %Y')}

                        Hiring Manager
                        {company_name}

                        Dear Hiring Manager,
                        [Continue with the body of the cover letter, tailored to the job description and resume.]

                        **My Resume:**
                        {resume_text}

                        **Job Description:**
                        {job_description}
                        """,
                        "Tailor Resume for Job": f"Act as a professional resume editor... tailor the following resume...\n\n**My Original Resume:**\n{resume_text}\n\n**Job Title:**\n{job_title}\n\n**Job Description:**\n{job_description}",
                        "Prepare for Interview": f"Act as an experienced hiring manager... Generate 10 interview questions...\n\n**My Resume:**\n{resume_text}\n\n**Job Description:**\n{job_description}"
                    }
                    prompt = prompts[action]

                    with st.spinner("🤖 Gemini is generating the first draft..."):
                        try:
                            response = st.session_state.chat_session.send_message(prompt)
                            st.session_state.messages.append({"role": "assistant", "content": response.text})
                            st.session_state.active_tab = "📄 AI Document Generator"
                            st.success("Draft generated!")
                        except Exception as e:
                            st.error(f"An error occurred with the Gemini API: {e}")
            else:
                st.error("Please provide all inputs in the sidebar.")

    # --- Main App Interface with Tabs ---
    st.title("AI Job Application Helper")
    
    tab1, tab2 = st.tabs(["📄 AI Document Generator", "🔍 Find a Job"])

    with tab1:
        # ... (Chat interface code remains the same) ...
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
                col1, col2 = st.columns([1, 1])
                with col1:
                    if st.button("Clear Chat History"):
                        st.session_state.messages = []
                        st.session_state.chat_session = None
                        st.rerun()
                with col2:
                    last_content = st.session_state.messages[-1]["content"]
                    file_name = f"{st.session_state.action_select.lower().replace(' ', '_')}_draft.md"
                    st.download_button("Download Latest Response", data=last_content, file_name=file_name)

    with tab2:
        st.header("Find Job Postings Online")
        st.markdown("Enter your desired job title and location to generate direct search links to popular job boards.")
        search_keywords = st.text_input("Keywords (e.g., Python Developer)")
        search_location = st.text_input("Location (e.g., Toronto, ON)")
        
        if st.button("Generate Job Search Links"):
            if search_keywords:
                st.markdown("---")
                st.subheader("Your Custom Job Search Links")

                # URL encode the search terms for safety
                encoded_keywords = quote(search_keywords)
                encoded_location = quote(search_location)

                # Generate URLs for popular job boards
                indeed_url = f"https://www.indeed.com/jobs?q={encoded_keywords}&l={encoded_location}"
                linkedin_url = f"https://www.linkedin.com/jobs/search/?keywords={encoded_keywords}&location={encoded_location}"
                google_url = f"https://www.google.com/search?q={encoded_keywords}+jobs+in+{encoded_location}&ibp=htl;jobs"

                # Display links in a clean format
                st.markdown(f"### [Search on Indeed]({indeed_url})")
                st.markdown(f"### [Search on LinkedIn]({linkedin_url})")
                st.markdown(f"### [Search on Google Jobs]({google_url})")
            else:
                st.error("Please enter search keywords to generate links.")

# --- Password Protection ---
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

# --- Main App Execution ---
if check_password():
    run_main_app()
