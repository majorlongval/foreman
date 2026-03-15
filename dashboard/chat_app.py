import os
import logging
import streamlit as st
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.agent_toolkits.github.toolkit import GitHubToolkit
from langchain_community.utilities.github import GitHubAPIWrapper

# Configure logging to stdout for visibility in container logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("FOREMAN_CHAT")

def check_auth():
    """
    Implements a basic password-based authentication layer.
    Requires CHAT_PASSWORD environment variable to be set.
    """
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.markdown("### Authentication Required")
        password = st.text_input("Enter Chat Password", type="password")
        if st.button("Login"):
            expected_password = os.getenv("CHAT_PASSWORD")
            if not expected_password:
                logger.error("CHAT_PASSWORD environment variable not set")
                st.error("Authentication configuration error. Contact administrator.")
                return
            
            if password == expected_password:
                st.session_state.authenticated = True
                logger.info("User successfully authenticated")
                st.rerun()
            else:
                logger.warning("Failed login attempt")
                st.error("Invalid password")
        st.stop()

def initialize_agent():
    """
    Initializes the LangChain agent with the GitHub toolkit.
    Configures tools for listing, reading, creating, and labeling issues.
    """
    try:
        # Check for mandatory environment variables
        # Using either App credentials or Personal Access Token
        has_app_creds = os.getenv("GITHUB_APP_ID") and os.getenv("GITHUB_APP_PRIVATE_KEY")
        has_token = os.getenv("GITHUB_ACCESS_TOKEN") or os.getenv("GITHUB_TOKEN")
        
        if not (has_app_creds or has_token):
            st.error("Missing GitHub credentials (App ID/Key or Access Token)")
            return None
        
        if not os.getenv("GITHUB_REPOSITORY"):
            st.error("Missing GITHUB_REPOSITORY environment variable")
            return None

        if not os.getenv("OPENAI_API_KEY"):
            st.error("Missing OPENAI_API_KEY environment variable")
            return None

        llm = ChatOpenAI(model="gpt-4o", temperature=0)
        
        # GitHubAPIWrapper automatically picks up credentials from env
        github_wrapper = GitHubAPIWrapper()
        toolkit = GitHubToolkit.from_github_api_wrapper(github_wrapper)
        tools = toolkit.get_tools()

        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are FOREMAN, an autonomous GitHub agent. "
                       "You help manage repositories by listing issues, reading issue content, "
                       "creating issues, and adding labels. Always be concise and professional. "
                       "Current repository: " + os.getenv("GITHUB_REPOSITORY", "unknown")),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])

        agent = create_openai_functions_agent(llm, tools, prompt)
        agent_executor = AgentExecutor(
            agent=agent, 
            tools=tools, 
            verbose=True, 
            handle_parsing_errors=True
        )
        
        logger.info("Agent executor initialized successfully")
        return agent_executor
    except Exception as e:
        logger.error(f"Failed to initialize agent: {e}", exc_info=True)
        st.error(f"Initialization error: {str(e)}")
        return None

def main():
    st.set_page_config(page_title="FOREMAN Chat", page_icon="🤖", layout="wide")
    
    # Sidebar Info
    st.sidebar.title("FOREMAN Dashboard")
    st.sidebar.info("Autonomous GitHub Management Interface")
    
    # Authentication
    try:
        check_auth()
    except Exception as e:
        logger.error(f"Auth system failure: {e}")
        st.error("Authentication system error.")
        st.stop()

    st.title("🤖 Chat Interface")

    # Conversation History Persistence
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    if "agent_executor" not in st.session_state:
        with st.spinner("Initializing agent..."):
            st.session_state.agent_executor = initialize_agent()

    # Reset Chat Button
    if st.sidebar.button("Clear Conversation"):
        st.session_state.messages = []
        logger.info("Conversation history cleared by user")
        st.rerun()

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Chat input
    if prompt := st.chat_input("Ask FOREMAN to do something (e.g., 'list issues', 'label #22 as bug')..."):
        # Add user message to history
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Generate response
        with st.chat_message("assistant"):
            try:
                if st.session_state.agent_executor:
                    # Format history for the prompt
                    history = []
                    # Pass context to maintain conversation
                    for msg in st.session_state.messages[:-1]: # exclude current prompt
                        role = "human" if msg["role"] == "user" else "ai"
                        history.append((role, msg["content"]))

                    with st.spinner("Processing request..."):
                        response = st.session_state.agent_executor.invoke({
                            "input": prompt,
                            "chat_history": history[-10:] # Last 10 messages for context
                        })
                        
                        answer = response.get("output", "I encountered an error generating a response.")
                        st.markdown(answer)
                        st.session_state.messages.append({"role": "assistant", "content": answer})
                        logger.info(f"Successfully responded to prompt: {prompt[:50]}")
                else:
                    error_msg = "Agent is not configured properly. Check environment variables."
                    st.error(error_msg)
                    logger.error(error_msg)
            except Exception as e:
                error_msg = f"Error processing request: {str(e)}"
                logger.error(error_msg, exc_info=True)
                st.error("An error occurred while communicating with the agent.")
                st.session_state.messages.append({"role": "assistant", "content": f"Sorry, I ran into an error: {str(e)}"})

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Main loop crashed: {e}", exc_info=True)
        st.error("A critical error occurred. The system logs have been updated.")