from pydantic import BaseModel, Field

from app.agents.state import AgentState
from app.agents.trace import emit_trace
from app.data.manifest import load_manifest
from app.llm.provider_factory import get_chat_model

NODE_NAME = "coordinator"


class PlanStepOutput(BaseModel):
    dataset_id: str = Field(description="The dataset id from the catalog, exactly as given")
    reason: str = Field(description="Why this dataset is relevant to the query")


class CoordinatorPlan(BaseModel):
    steps: list[PlanStepOutput] = Field(
        description="Datasets relevant to answering the query. Pick only datasets "
        "that are actually needed; do not include irrelevant ones."
    )


def _format_catalog(manifest: list[dict]) -> str:
    lines = []
    for entry in manifest:
        columns = ", ".join(entry.get("column_meta", {}).keys()) or "(see topic)"
        lines.append(
            f"- id: {entry['id']}\n"
            f"  title: {entry['title']}\n"
            f"  topic: {', '.join(entry.get('topic', []))}\n"
            f"  columns: {columns}\n"
            f"  mode: {entry.get('mode', 'file')}"
        )
    return "\n".join(lines)


async def coordinator_node(state: AgentState) -> AgentState:
    manifest = load_manifest()
    catalog = _format_catalog(manifest)

    emit_trace(
        state,
        NODE_NAME,
        "reasoning",
        f"Matching query against {len(manifest)} catalogued datasets to decide which are relevant.",
    )

    model = get_chat_model(model_tier="fast").with_structured_output(CoordinatorPlan)
    prompt = (
        "You are a policy data research coordinator. Given a user's question and a "
        "catalog of available government datasets, decide which dataset(s) are "
        "relevant to answering it. Pick only what's needed - not every dataset.\n\n"
        f"Available datasets:\n{catalog}\n\n"
        f"User question: {state['query']}"
    )

    result: CoordinatorPlan = await model.ainvoke(prompt)
    state["plan"] = [{"dataset_id": s.dataset_id, "reason": s.reason} for s in result.steps]

    if not state["plan"]:
        state["errors"].append(
            {"node_name": NODE_NAME, "message": "No relevant dataset found for this query."}
        )

    chosen = ", ".join(f"{s['dataset_id']} ({s['reason']})" for s in state["plan"]) or "none"
    emit_trace(state, NODE_NAME, "action", f"Selected dataset(s): {chosen}")

    return state
