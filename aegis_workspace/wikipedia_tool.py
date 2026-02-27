import wikipedia
from langchain.tools import tool

@tool
def search_wikipedia(query: str) -> str:
    """Run Wikipedia search and get page summaries."""
    try:
        # Limiting to 2 sentences for concise results
        summary = wikipedia.summary(query, sentences=2)
        return summary
    except wikipedia.exceptions.PageError:
        return f"Error: Page titled '{query}' not found."
    except wikipedia.exceptions.DisambiguationError as e:
        return f"Error: '{query}' is ambiguous. Options: {e.options[:5]}"
    except Exception as e:
        return f"An unexpected error occurred: {e}"

if __name__ == '__main__':
    # Test the tool with a common query
    test_query = "Artificial Intelligence"
    print(f"Testing with query: '{test_query}'")
    result = search_wikipedia.run(test_query)
    print("Result:")
    print(result)
    # Test a failing case
    fail_query = "NonExistentPageAbc123"
    print(f"\nTesting with non-existent page: '{fail_query}'")
    fail_result = search_wikipedia.run(fail_query)
    print("Result:")
    print(fail_result)
