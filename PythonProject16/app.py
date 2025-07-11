```python
import streamlit as st
import google.generativeai as genai
import PyPDF2
import io
import requests

# --- Page Configuration ---
st.set_page_config(layout="wide", page_title="Interactive Job Application Helper")

# --- Custom CSS for Fonts and Styling ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="st-"] {
    font-family: 'Inter', sans-serif;
}
.st-emotion-cache-1y4p8pa {
    padding-top: 2rem; /* Adjust top padding */
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
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        page_content = response.text[:20000]  # Limit content size to avoid token limits
        extract_prompt = f"""
        Extract the job title and the full job description from the following webpage content.
        Ignore ads, navigation, and irrelevant sections. Output exactly in this format:
        Job Title: [title here]
        Job Description: [description here]
        
        Webpage Content:
        {page_content}
        """
        extract_response = model.generate_content(extract_prompt)
        text = extract_response.text.strip()
        lines = text.split('\n')
        job_title = lines[0].replace("Job Title: ", "").strip() if lines else ""
        job_description = '\n'.join(lines[1:]).replace("Job Description: ", "").strip() if len(lines) > 1 else ""
        return job_title, job_description
    except Exception as e:
        st.error(f"Error fetching or extracting job details: {e}")
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

    # --- Streamlit App UI ---
    st.title("📄 Interactive Job Application Helper")
    st.markdown(
        "Upload your resume, provide job details (paste or fetch from URL), and get AI assistance. Then, chat with the AI to refine the results.")

    # --- Model Selection ---
    model = genai.GenerativeModel('gemini-1.5-flash-latest')

    # --- Initialize Session State ---
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "chat_session" not in st.session_state:
        st.session_state.chat_session = None
    if "fetched_job_title" not in st.session_state:
        st.session_state.fetched_job_title = ""
    if "fetched_job_description" not in st.session_state:
        st.session_state.fetched_job_description = ""

    # --- Layout ---
    with st.sidebar:
        st.header("Your Details & Job Info")
        resume_file = st.file_uploader("Upload Resume (TXT or PDF)", type=["txt", "pdf"])
        
        st.subheader("Job Details")
        job_url = st.text_input("Job Posting URL (optional)")
        if st.button("Fetch Job Details") and job_url:
            with st.spinner("Fetching and extracting job details..."):
                fetched_title, fetched_desc = fetch_job_details_from_url(job_url, model)
                if fetched_title and fetched_desc:
                    st.session_state.fetched_job_title = fetched_title
                    st.session_state.fetched_job_description = fetched_desc
                    st.rerun()
        
        job_title = st.text_input("Job Title", value=st.session_state.fetched_job_title)
        job_description = st.text_area("Job Description", height=200, value=st.session_state.fetched_job_description)
        
        action = st.selectbox(
            "What do you need help with?",
            ["Generate Cover Letter", "Tailor Resume for Job", "Prepare for Interview"],
            key="action_select"
        )

        if st.button("✨ Generate Initial Draft", use_container_width=True):
            if resume_file and job_title and job_description:
                with st.spinner("Reading resume..."):
                    if resume_file.name.endswith(".txt"):
                        resume_text = resume_file.read().decode("utf-8")
                    else:
                        resume_text = read_pdf(resume_file)

                if resume_text:
                    st.session_state.chat_session = model.start_chat(history=[])
                    st.session_state.messages = []

                    if action == "Generate Cover Letter":
                        prompt = f"""
                        Act as a professional career coach. Based on the resume below and the provided job description, write a compelling and professional cover letter.
                        The tone should be enthusiastic but professional. Highlight the key qualifications from the resume that match the job description.

                        **My Resume:**
                        {resume_text}

                        **Job Title:**
                        {job_title}

                        **Job Description:**
                        {job_description}
                        """
                    elif action == "Tailor Resume for Job":
                        prompt = f"""
                        Act as a professional resume editor. Your task is to tailor the following resume to better match the given job description.
                        Focus on highlighting the most relevant skills and experiences. Rephrase bullet points to include keywords from the job description where appropriate.
                        Output the complete, updated resume text in Markdown format.

                        **My Original Resume:**
                        {resume_text}

                        **Job Title:**
                        {job_title}

                        **Job Description:**
                        {job_description}
                        """
                    else:  # Prepare for Interview
                        prompt = f"""
                        Act as an experienced hiring manager. Generate 10 common and insightful interview questions for the '{job_title}' role, based on the provided job description and my resume.
                        For each question, provide a sample answer that leverages the experience outlined in my resume. Format the output clearly with each question followed by its sample answer.

                        **My Resume:**
                        {resume_text}

                        **Job Description:**
                        {job_description}
                        """

                    with st.spinner("🤖 Gemini is generating the first draft..."):
                        try:
                            response = st.session_state.chat_session.send_message(prompt)
                            st.session_state.messages.append({"role": "assistant", "content": response.text})
                            st.success("Draft generated! You can now chat below to customize it.")
                        except Exception as e:
                            st.error(f"An error occurred with the Gemini API: {e}")
            else:
                st.error("Please provide all inputs in the sidebar.")

        # --- Job Search Section ---
        st.header("Job Search")
        search_keywords = st.text_input("Search Keywords (e.g., Software Engineer)")
        search_location = st.text_input("Location (e.g., New York)")
        if st.button("Generate Job Search Links"):
            if search_keywords:
                indeed_url = f"https://www.indeed.com/jobs?q={search_keywords.replace(' ', '+')}&l={search_location.replace(' ', '+')}"
                linkedin_url = f"https://www.linkedin.com/jobs/search/?keywords={search_keywords.replace(' ', '%20')}&location={search_location.replace(' ', '%20')}"
                google_url = f"https://www.google.com/search?q={search_keywords.replace(' ', '+')}+jobs+in+{search_location.replace(' ', '+')}"
                st.markdown(f"[Search on Indeed]({indeed_url})")
                st.markdown(f"[Search on LinkedIn]({linkedin_url})")
                st.markdown(f"[Search on Google]({google_url})")
            else:
                st.error("Please enter search keywords.")

    # --- Main Chat Interface ---
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

        # --- Additional Chat Features ---
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Clear Chat"):
                st.session_state.messages = []
                st.session_state.chat_session = model.start_chat(history=[])
                st.rerun()
        with col2:
            if st.session_state.messages:
                last_content = st.session_state.messages[-1]["content"]
                st.download_button("Download Latest Response", data=last_content, file_name=f"{action.lower().replace(' ', '_')}_draft.md")

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
```
