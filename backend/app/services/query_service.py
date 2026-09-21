import uuid

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.parsers.csv_parser import read_csv
from app.llm.provider_factory import get_chat_model
from app.models.analysis_run import AnalysisRun
from app.models.dataset import Dataset


async def run_query(session: AsyncSession, query_text: str) -> AnalysisRun:
    dataset = await session.scalar(
        select(Dataset).where(Dataset.dataset_key == "retrenchment_by_industry")
    )
    if dataset is None or dataset.raw_cache_path is None:
        raise RuntimeError(
            "No seeded dataset found. Run `python -m scripts.seed_datasets` first."
        )

    df: pd.DataFrame = read_csv(dataset.raw_cache_path)
    sample = df.head(20).to_csv(index=False)

    model = get_chat_model(model_tier="quality")
    prompt = (
        "You are a policy data analyst. You are given a sample of a government "
        f"dataset titled '{dataset.title}' (columns: {', '.join(df.columns)}).\n\n"
        f"Sample data (CSV):\n{sample}\n\n"
        f"User question: {query_text}\n\n"
        "Answer using only the data shown above. If the sample doesn't contain enough "
        "information to answer fully, say so explicitly rather than guessing."
    )
    response = await model.ainvoke(prompt)

    run = AnalysisRun(
        id=uuid.uuid4(),
        query_text=query_text,
        provider_used="openai",
        status="completed",
        report_markdown=response.content,
    )
    session.add(run)
    await session.commit()
    return run
