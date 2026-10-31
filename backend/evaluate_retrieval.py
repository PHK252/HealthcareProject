import sys

from main import retrieve_relevant_chunks


# Manually labeled relevant chunk IDs for document 6.
# Update these labels if the document or chunking changes.
EVALUATION_SET = [
    {
        "question": "When should I schedule my follow-up appointment?",
        "relevant_chunks": {1, 2},
    },
    {
        "question": "What symptoms should I watch for?",
        "relevant_chunks": {3},
    },
    {
        "question": "What should I do about my wrist?",
        "relevant_chunks": {2},
    },
    {
        "question": "What medication instructions are provided?",
        "relevant_chunks": {2, 3},
    },
    {
        "question": "What dosage of ibuprofen should I take?",
        "relevant_chunks": set(),
    },
]


def evaluate_retrieval(document_id: int, top_k: int = 3):
    total_relevant = 0
    total_retrieved_relevant = 0
    reciprocal_ranks = []
    answerable_questions = 0
    unanswerable_correct = 0

    print(f"\nEvaluating document ID: {document_id}")
    print("=" * 80)

    for item in EVALUATION_SET:
        question = item["question"]
        relevant = item["relevant_chunks"]

        results = retrieve_relevant_chunks(
            query=question,
            top_k=top_k,
            document_id=document_id,
        )

        retrieved_ids = [chunk["chunk_id"] for chunk in results]
        relevant_ranks = [
            rank
            for rank, chunk_id in enumerate(retrieved_ids, start=1)
            if chunk_id in relevant
        ]

        print(f"\nQUESTION: {question}")
        print(f"Relevant chunk IDs: {sorted(relevant)}")
        print(f"Retrieved chunk IDs: {retrieved_ids}")

        if relevant:
            answerable_questions += 1
            total_relevant += len(relevant)

            hits = len(set(retrieved_ids) & relevant)
            total_retrieved_relevant += hits

            reciprocal_rank = (
                1 / relevant_ranks[0] if relevant_ranks else 0
            )
            reciprocal_ranks.append(reciprocal_rank)

            print(f"Relevant chunks retrieved: {hits}/{len(relevant)}")
            print(f"Reciprocal rank: {reciprocal_rank:.3f}")
        else:
            correct_abstention = len(results) == 0
            unanswerable_correct += int(correct_abstention)
            print(
                "Correct abstention:",
                "YES" if correct_abstention else "NO",
            )

    recall_at_k = (
        total_retrieved_relevant / total_relevant
        if total_relevant else 0
    )

    precision_at_k = (
        total_retrieved_relevant / (answerable_questions * top_k)
        if answerable_questions else 0
    )

    mrr = (
        sum(reciprocal_ranks) / answerable_questions
        if answerable_questions else 0
    )

    print("\n" + "=" * 80)
    print(f"RETRIEVAL EVALUATION (Top {top_k})")
    print("=" * 80)
    print(f"Recall@{top_k}: {recall_at_k:.3f}")
    print(f"Precision@{top_k}: {precision_at_k:.3f}")
    print(f"MRR: {mrr:.3f}")
    print(
        "Correct abstentions:",
        f"{unanswerable_correct}/1",
    )


if __name__ == "__main__":
    document_id = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    evaluate_retrieval(document_id)