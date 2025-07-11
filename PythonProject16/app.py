import streamlit as st
import google.generativeai as genai
import PyPDF2
import io
import requests

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

def fetch_job_details_from_url(url, model):
    """Fetches and extracts job title and description from a URL using Gemini."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # A simple way to get the main content, not perfect but often effective
        from bs4 import BeautifulSoup
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
        
        if lines[0].startswith("Job Title:"):
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

def run_main_app():
    """The main application logic after successful authentication."""
    # --- Gemini API Configuration ---
    try:
        GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
        genai.configure(api_key=GEMINI_API_KEY)
    except (FileNotFoundError, KeyError):
        st.warning("GEMINI_API_KEY not found in st.secrets. Please add it to your .streamlit/secrets.toml file.")
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
        resume_file = st.file_uploader("1. Upload Resume (TXT or PDF)", type=["txt", "pdf"])
        
        st.header("Job Details")
        st.markdown("Enter details manually or fetch from a URL.")
        
        job_url = st.text_input("Job Posting URL (optional)")
        if st.button("Fetch from URL") and job_url:
            with st.spinner("Fetching and extracting job details..."):
                title, desc = fetch_job_details_from_url(job_url, model)
                if title and desc:
                    st.session_state.fetched_job_title = title
                    st.session_state.fetched_job_description = desc
                    st.success("Job details fetched!")
                else:
                    st.error("Could not extract details. Please paste them manually.")
        
        job_title = st.text_input("Job Title", value=st.session_state.fetched_job_title)
        job_description = st.text_area("Job Description", height=200, value=st.session_state.fetched_job_description)
        
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
                    
                    prompts = {
                        "Generate Cover Letter": f"Act as a professional career coach... write a compelling cover letter...\n\n**My Resume:**\n{resume_text}\n\n**Job Title:**\n{job_title}\n\n**Job Description:**\n{job_description}",
                        "Tailor Resume for Job": f"Act as a professional resume editor... tailor the following resume...\n\n**My Original Resume:**\n{resume_text}\n\n**Job Title:**\n{job_title}\n\n**Job Description:**\n{job_description}",
                        "Prepare for Interview": f"Act as an experienced hiring manager... Generate 10 interview questions...\n\n**My Resume:**\n{resume_text}\n\n**Job Description:**\n{job_description}"
                    }
                    prompt = prompts[action]

                    with st.spinner("🤖 Gemini is generating the first draft..."):
                        try:
                            response = st.session_state.chat_session.send_message(prompt)
                            st.session_state.messages.append({"role": "assistant", "content": response.text})
                            st.success("Draft generated! You can now chat below to customize it.")
                        except Exception as e:
                            st.error(f"An error occurred with the Gemini API: {e}")
            else:
                st.error("Please provide all inputs in the sidebar.")

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
            
            # --- Chat Controls ---
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
                    file_name = f"{action.lower().replace(' ', '_')}_draft.md"
                    st.download_button("Download Latest Response", data=last_content, file_name=file_name)

    with tab2:
        st.header("Search for Job Postings")
        search_keywords = st.text_input("Keywords (e.g., Software Engineer)")
        search_location = st.text_input("Location (e.g., New York, NY)")
        if st.button("Generate Job Search Links"):
            if search_keywords:
                st.markdown("---")
                indeed_url = f"https://www.indeed.com/jobs?q={search_keywords.replace(' ', '+')}&l={search_location.replace(' ', '+')}"
                linkedin_url = f"https://www.linkedin.com/jobs/search/?keywords={search_keywords.replace(' ', '%20')}&location={search_location.replace(' ', '%20')}"
                google_url = f"https://www.google.com/search?q={search_keywords.replace(' ', '+')}+jobs+in+{search_location.replace(' ', '+')}&ibp=htl;jobs"
                st.markdown(f"#### [Search on Indeed]({indeed_url})")
                st.markdown(f"#### [Search on LinkedIn]({linkedin_url})")
                st.markdown(f"#### [Search on Google Jobs]({google_url})")
            else:
                st.error("Please enter search keywords.")

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
