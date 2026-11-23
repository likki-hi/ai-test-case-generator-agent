"""AI Test Case Generator Agent - Streamlit UI."""
import streamlit as st

import database
from agent import LLMError, TestCaseAgent
from export_utils import finalize, find_problems, to_csv_bytes, to_dataframe
from test_case_generator import PRIORITIES, SCENARIOS, ValidationError

st.set_page_config(page_title="AI Test Case Generator Agent", page_icon="🧪", layout="wide")
database.init_db()

DEFAULTS = {"df": None, "analysis": None, "trace": [], "req_text": "", "req_id": None,
            "clarification": None, "editor_version": 0}
for key, value in DEFAULTS.items():
    st.session_state.setdefault(key, value)


def set_results(df, analysis, trace, req_id=None, req_text=None):
    st.session_state.df = df
    st.session_state.analysis = analysis
    st.session_state.trace = trace
    st.session_state.req_id = req_id
    st.session_state.clarification = None
    st.session_state.editor_version += 1  # reset the data editor for the new table
    if req_text is not None:
        st.session_state.req_text = req_text


def run_generation(requirement: str, model: str, max_cases: int, force: bool = False):
    if not requirement.strip():
        st.warning("Please enter a software requirement first.")
        return
    try:
        with st.spinner("The agent is analysing the requirement and generating test cases..."):
            result = TestCaseAgent(model=model).run(requirement, force=force, max_cases=max_cases)
    except ValueError as exc:
        st.warning(str(exc))
        return
    except (LLMError, ValidationError) as exc:
        st.error(str(exc))
        return
    except Exception as exc:  # never crash the app
        st.error(f"Unexpected error: {exc}")
        return

    if result.status == "needs_clarification":
        st.session_state.clarification = result.clarification
        st.session_state.trace = result.trace
        return
    set_results(to_dataframe(result.test_cases), result.analysis, result.trace, None, requirement)


# ---------------- Sidebar: settings + history ----------------
with st.sidebar:
    st.header("Settings")
    model = st.text_input("Ollama model", value="llama3.2",
                          help="Any model you have pulled, e.g. llama3.2, mistral, qwen2.5")
    max_cases = st.slider("Max test cases", 3, 20, 6)

    st.header("History")
    history = database.list_requirements()
    if not history:
        st.caption("No saved requirements yet.")
    for item in history:
        with st.container(border=True):
            st.markdown(f"**{item['feature'] or 'Requirement'}** · {item['n']} cases")
            st.caption(f"{item['created_at']}  \n{item['requirement'][:80]}")
            col1, col2 = st.columns(2)
            if col1.button("Load", key=f"load_{item['id']}"):
                req, df = database.load_requirement(item["id"])
                set_results(df, {"feature": req["feature"], "assumptions": [a for a in (req["assumptions"] or "").split("\n") if a]},
                            ["Loaded from history"], item["id"], req["requirement"])
                st.rerun()
            if col2.button("Delete", key=f"del_{item['id']}"):
                database.delete_requirement(item["id"])
                if st.session_state.req_id == item["id"]:
                    st.session_state.req_id = None
                st.rerun()

# ---------------- Main page ----------------
st.title("🧪 AI Test Case Generator Agent")
st.write("Describe a software feature in plain English. The agent understands it, chooses positive, "
         "negative and edge scenarios, and generates test cases you can review, edit, save and export.")

requirement = st.text_area("Software requirement", value=st.session_state.req_text, height=120,
                           placeholder="Example: A user should be able to register using name, email, and password.")

if st.button("Generate Test Cases", type="primary"):
    st.session_state.req_text = requirement
    run_generation(requirement, model, max_cases)

if st.session_state.clarification:
    st.warning("The requirement needs more detail: " + st.session_state.clarification)
    st.caption("Edit the requirement above and generate again, or let the agent continue with clearly stated assumptions.")
    if st.button("Generate anyway (use assumptions)"):
        run_generation(st.session_state.req_text or requirement, model, max_cases, force=True)

if st.session_state.df is not None:
    analysis = st.session_state.analysis or {}
    with st.expander("Agent analysis and steps", expanded=False):
        st.markdown(f"**Feature:** {analysis.get('feature', '-')}")
        if analysis.get("main_purpose"):
            st.markdown(f"**Testing purpose:** {analysis['main_purpose']}")
        if analysis.get("conditions"):
            st.markdown("**Conditions:**\n" + "\n".join(f"- {c}" for c in analysis["conditions"]))
        if analysis.get("assumptions"):
            st.markdown("**Assumptions (not in the requirement):**\n" + "\n".join(f"- {a}" for a in analysis["assumptions"]))
        if analysis.get("scenario_categories"):
            st.markdown("**Scenario categories chosen:** " + ", ".join(analysis["scenario_categories"]))
        st.markdown("**Agent steps:**\n" + "\n".join(f"- {t}" for t in st.session_state.trace))

    st.subheader("Test cases")
    st.caption("Click a cell to edit. To delete a row, select it (left edge) and press Delete. "
               "AI-generated test cases must be reviewed by a human before real testing.")
    edited = st.data_editor(
        st.session_state.df, num_rows="dynamic", use_container_width=True, hide_index=True,
        key=f"editor_{st.session_state.editor_version}",
        column_config={
            "ID": st.column_config.TextColumn(disabled=True, width="small"),
            "Scenario": st.column_config.SelectboxColumn(options=SCENARIOS, width="small"),
            "Steps": st.column_config.TextColumn(width="large"),
            "Priority": st.column_config.SelectboxColumn(options=PRIORITIES, width="small"),
        })
    final_df = finalize(edited)
    problems = find_problems(final_df)
    if final_df.empty:
        st.info("The table is empty. Generate test cases or load one from history.")
    for p in problems:
        st.error(p)

    save_col, dl_col = st.columns(2)
    disabled = final_df.empty or bool(problems)
    if save_col.button("Save to history", disabled=disabled):
        try:
            if st.session_state.req_id:
                database.update_cases(st.session_state.req_id, final_df)
                st.success("Updated the saved test cases.")
            else:
                st.session_state.req_id = database.save_new(
                    st.session_state.req_text, analysis.get("feature", ""),
                    analysis.get("assumptions", []), final_df)
                st.success("Saved. It now appears under History.")
        except Exception as exc:
            st.error(f"Could not save: {exc}")
    dl_col.download_button("Download CSV", data=to_csv_bytes(final_df), file_name="test_cases.csv",
                           mime="text/csv", disabled=disabled)