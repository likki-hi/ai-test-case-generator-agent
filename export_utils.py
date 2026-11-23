"""DataFrame clean-up, validation of user edits and CSV export."""
import pandas as pd

from test_case_generator import COLUMNS, PRIORITIES, SCENARIOS


def to_dataframe(cases: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(cases, columns=COLUMNS).fillna("").astype(str)


def finalize(df: pd.DataFrame) -> pd.DataFrame:
    """Drop blank rows and renumber IDs (rows may have been added or deleted in the editor)."""
    df = df.reindex(columns=COLUMNS).fillna("").astype(str)
    df = df[df[["Title", "Steps", "Expected Result"]].apply(lambda c: c.str.strip()).ne("").any(axis=1)]
    df = df.reset_index(drop=True)
    df["ID"] = [f"TC-{i:02d}" for i in range(1, len(df) + 1)]
    df.loc[df["Priority"] == "", "Priority"] = "Medium"
    df.loc[df["Scenario"] == "", "Scenario"] = "Positive"
    return df


def find_problems(df: pd.DataFrame) -> list[str]:
    problems = []
    for _, row in df.iterrows():
        for col in ("Title", "Steps", "Expected Result"):
            if not row[col].strip():
                problems.append(f"{row['ID']}: '{col}' is empty")
        if row["Priority"] not in PRIORITIES:
            problems.append(f"{row['ID']}: priority must be High, Medium or Low")
        if row["Scenario"] not in SCENARIOS:
            problems.append(f"{row['ID']}: scenario must be Positive, Negative or Edge")
    return problems


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    # utf-8-sig so Excel opens it correctly
    return df.to_csv(index=False).encode("utf-8-sig")
