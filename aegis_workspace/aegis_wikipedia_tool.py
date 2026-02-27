import wikipedia
from langchain.tools import tool
from typing import List

# Set a custom User-Agent to avoid being blocked
wikipedia.set_user_agent("AegisBot/1.0 (https://github.com/waldo-context-squad/aegis)")

@tool
def query_wikipedia(query: str, mode: str = 'summary') -> str | List[str]:
    """Queries the Wikipedia API.

    Args:
        query (str): The search query.
        mode (str): The query mode. Can be 'summary', 'search', or 'full'.
            - 'summary': Returns a short summary of the best matching page (default).
            - 'search': Returns a list of potential page titles.
            - 'full': Returns the full text content of the best matching page.

    Returns:
        str | List[str]: The result of the query. A string for 'summary' and 'full' modes, 
                         and a list of strings for 'search' mode.
    """
    try:
        if mode == 'summary':
            # The wikipedia library can be aggressive with auto-suggest.
            # A direct page lookup is better for precise topics.
            try:
                return wikipedia.summary(query, auto_suggest=False)
            except wikipedia.exceptions.PageError:
                # If the exact title doesn't work, fall back to auto_suggest
                return wikipedia.summary(query, auto_suggest=True)
        elif mode == 'search':
            return wikipedia.search(query)
        elif mode == 'full':
            page = wikipedia.page(query, auto_suggest=False)
            return page.content
        else:
            return "Error: Invalid mode specified. Use 'summary', 'search', or 'full'."
    except wikipedia.exceptions.PageError:
        return f"Error: Could not find a page matching '{query}'. Try a broader search with mode='search'."
    except wikipedia.exceptions.DisambiguationError as e:
        return f"Error: '{query}' is ambiguous. Options: {e.options[:5]}"
    except Exception as e:
        return f"An unexpected error occurred: {e}"

if __name__ == '__main__':
    print("--- Running Wikipedia Tool Tests ---")

    # Test 1: Summary
    print("\n[Test 1: Summary] Querying for 'Python (programming language)'...")
    summary_query = "Python (programming language)"
    summary_result = query_wikipedia(query=summary_query, mode='summary')
    print(f"Result (first 150 chars): {summary_result[:150]}...")
    assert "high-level, general-purpose programming language" in summary_result
    print("Test 1 PASSED.")

    # Test 2: Search
    print("\n[Test 2: Search] Querying for 'Aegis'...")
    search_query = "Aegis"
    search_result = query_wikipedia(query=search_query, mode='search')
    print(f"Result: {search_result}")
    assert isinstance(search_result, list)
    assert "Aegis" in search_result
    print("Test 2 PASSED.")

    # Test 3: Full Content (using a more stable page title)
    print("\n[Test 3: Full Content] Querying for 'Artificial intelligence'...")
    content_query = "Artificial intelligence"
    content_result = query_wikipedia(query=content_query, mode='full')
    print(f"Result (first 150 chars): {content_result[:150]}...")
    assert "branch of computer science" in content_result
    print("Test 3 PASSED.")

    # Test 4: Error Handling - Page Not Found
    print("\n[Test 4: Page Not Found] Querying for a non-existent page...")
    error_query = "AegisNonExistentPageAbc123"
    error_result = query_wikipedia(query=error_query, mode='summary')
    print(f"Result: {error_result}")
    assert "Error: Could not find a page matching" in error_result
    print("Test 4 PASSED.")

    print("\n--- All tests completed successfully. ---")
