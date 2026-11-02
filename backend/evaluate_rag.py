from main import retrieve_relevant_chunks

TEST_CASES = [
    {
        "question": "When should the patient arrange a follow-up appointment?",
        "expected_document_id": 16,
        "expected_chunk_id": 41,
    },
    {
        "question": "What activities should the patient avoid?",
        "expected_document_id": 16,
        "expected_chunk_id": 42,
    },
    {
        "question": "What ankle support should the patient use?",
        "expected_document_id": 16,
        "expected_chunk_id": 42,
    },
    {
        "question": "What symptoms require urgent medical assessment?",
        "expected_document_id": 16,
        "expected_chunk_id": 43,
    },
    {
        "question": "What is the clinic's phone number and business hours?",
        "expected_document_id": 16,
        "expected_chunk_id": 43,
    },
        {
        "question": "How soon does the patient need to see the clinic again?",
        "expected_document_id": 16,
        "expected_chunk_id": 41,
    },
    {
        "question": "Which physical activities could make the ankle worse?",
        "expected_document_id": 16,
        "expected_chunk_id": 42,
    },
    {
        "question": "What changes in the foot's color or sensation are warning signs?",
        "expected_document_id": 16,
        "expected_chunk_id": 43,
    },
    {
        "question": "What should the patient do if they can no longer stand on the injured foot?",
        "expected_document_id": 16,
        "expected_chunk_id": 43,
    },
    {
        "question": "Was the patient prescribed any new medication?",
        "expected_document_id": 16,
        "expected_chunk_id": 42,
    },
]

def evaluate_retrieval():
    results = []

    for test in TEST_CASES:
        retrieved = retrieve_relevant_chunks(
            query=test["question"],
            top_k=3,
            document_id=test["expected_document_id"],
        )

        expected_chunk_id = test["expected_chunk_id"]

        rank = next(
            (
                i
                for i, chunk in enumerate(retrieved, start=1)
                if chunk["chunk_id"] == expected_chunk_id
            ),
            0,
        )

        results.append(rank)

        print("\nQuestion:", test["question"])
        print("Expected chunk:", expected_chunk_id)
        print(
            "Retrieved chunks:",
            [
                (c["chunk_id"], round(c["score"], 3))
                for c in retrieved
            ],
            )
        print("Correct chunk rank:", rank if rank else "Not retrieved")

    if results:
        recall = sum(rank > 0 for rank in results) / len(results)
        mrr = sum(1 / rank if rank > 0 else 0 for rank in results) / len(results)

        print(f"\nRecall@3: {recall:.2%}")
        print(f"MRR@3: {mrr:.2f}")
    else:
        print("No test cases added yet.")


if __name__ == "__main__":
    evaluate_retrieval()