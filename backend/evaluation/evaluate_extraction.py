import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import pymupdf

# Allow this script to import functions from backend/main.py
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from main import identify_task_candidates, extract_tasks_with_ollama


def normalize_text(text: str) -> str:
    """Normalize text for comparison without changing its meaning."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def token_f1(prediction: str, expected: str) -> float:
    """Calculate token-level F1 between a prediction and an annotation."""
    predicted_tokens = set(normalize_text(prediction).split())
    expected_tokens = set(normalize_text(expected).split())

    if not predicted_tokens or not expected_tokens:
        return 0.0

    overlap = len(predicted_tokens & expected_tokens)

    precision = overlap / len(predicted_tokens)
    recall = overlap / len(expected_tokens)

    if precision + recall == 0:
        return 0.0

    return 2 * precision * recall / (precision + recall)


def evaluate_predictions(predictions, expected_tasks, method):
    """Match predictions to ground truth and calculate extraction metrics."""

    matches = []
    possible_matches = []

    for pred_index, prediction in enumerate(predictions):
        for expected_index, expected in enumerate(expected_tasks):
            score = token_f1(
                prediction["source_quote"],
                expected["source_quote"],
            )

            if score >= 0.80:
                possible_matches.append(
                    (score, pred_index, expected_index)
                )

    # Greedy one-to-one matching, highest similarity first.
    possible_matches.sort(reverse=True)

    used_predictions = set()
    used_expected = set()

    for score, pred_index, expected_index in possible_matches:
        if (
            pred_index in used_predictions
            or expected_index in used_expected
        ):
            continue

        used_predictions.add(pred_index)
        used_expected.add(expected_index)

        matches.append({
            "prediction": predictions[pred_index]["source_quote"],
            "expected": expected_tasks[expected_index]["source_quote"],
            "similarity": round(score, 3),
        })

    true_positives = len(matches)
    false_positives = len(predictions) - true_positives
    false_negatives = len(expected_tasks) - true_positives

    precision = (
        true_positives / (true_positives + false_positives)
        if true_positives + false_positives else 0
    )

    recall = (
        true_positives / (true_positives + false_negatives)
        if true_positives + false_negatives else 0
    )

    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall else 0
    )

    return {
        "method": method,
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "matches": matches,
        "unmatched_predictions": [
            p["source_quote"]
            for i, p in enumerate(predictions)
            if i not in used_predictions
        ],
        "missed_expected_tasks": [
            e["source_quote"]
            for i, e in enumerate(expected_tasks)
            if i not in used_expected
        ],
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "pdf",
        help="Path to the discharge-instructions PDF",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    ground_truth_path = Path(__file__).parent / "ground_truth.json"

    with open(ground_truth_path, "r", encoding="utf-8") as file:
        ground_truth = json.load(file)

    expected_tasks = ground_truth["expected_tasks"]

    # Extract PDF text and preserve page boundaries.
    pdf = pymupdf.open(pdf_path)

    pages = [
        {
            "page": index + 1,
            "text": page.get_text(),
        }
        for index, page in enumerate(pdf)
    ]

    pdf.close()

    # Run the existing regex baseline.
    regex_candidates = identify_task_candidates(pages)

    regex_predictions = [
        {
            "source_quote": candidate["source_quote"],
        }
        for candidate in regex_candidates
    ]

    # Run Ollama extraction.
    llm_result = await extract_tasks_with_ollama(pages)

    llm_predictions = [
        {
            "source_quote": candidate["source_quote"],
        }
        for candidate in llm_result["tasks"]
    ]

    # Evaluate both methods against the same annotations.
    regex_results = evaluate_predictions(
        regex_predictions,
        expected_tasks,
        "Regex baseline",
    )

    llm_results = evaluate_predictions(
        llm_predictions,
        expected_tasks,
        "Ollama Llama 3.2",
    )

    report = {
        "document": pdf_path.name,
        "expected_task_count": len(expected_tasks),
        "results": [
            regex_results,
            llm_results,
        ],
    }

    print(json.dumps(report, indent=2))

    # Save the evaluation report.
    output_path = Path(__file__).parent / "evaluation_report.json"

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)

    print(f"\nReport saved to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())