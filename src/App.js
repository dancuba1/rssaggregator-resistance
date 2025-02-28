import React, { useEffect, useState } from "react";
import "./App.css";
import { TextInput } from "./components/TextInput";
import { Search } from "./components/Search";
import { WordCloud } from "./components/WordCloud";
import { SyntaxExplanation } from "./components/SyntaxExplanation";

function App() {
  const [query, setQuery] = useState(""); // Track the search input
  const [articles, setArticles] = useState([]); // Store articles
  const [loading, setLoading] = useState(false); // Loading state

  const [tags, setTags] = useState([]);
  const [error, setError] = useState(null);
  
  useEffect(() => {
    async function getTags() {
      try {
        const response = await fetch("https://aggregatorapi.onrender.com/count_tags");
        if (!response.ok) {
          const errorText = await response.text();
          setError("Failed to fetch tags: " + errorText);
          return;
        }
        const data = await response.json();
        if (data && typeof data === "object") {
          setTags(data);
        }
      } catch (error) {
        setError("Network error: " + error.message);
      }
    }
    getTags();
  }, []);

  const [noResults, setNoResults] = useState(false); // State for error message

  async function searchFeeds() {
    // Show 3 empty placeholders immediately
    setLoading(true);
    setNoResults(false);
    setArticles([{},{},{}]); 

    try {
      const response = await fetch(`https://aggregatorapi.onrender.com/search?query=${encodeURIComponent(query)}`);
      if (!response.ok) {
        console.error("API Error:", await response.text());
        return;
      }
      const data = await response.json();
      if (data.length === 0) {
        setNoResults(true);
        setArticles([]);
        return;
      }
      setArticles(data); // Update with actual articles
    } catch (error) {
      console.error("Error fetching feeds:", error);
      setNoResults(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div id="rss-aggregator">
      <SyntaxExplanation/>
      <div className="word-cloud-container">
        <div className="word-cloud">
          {tags.length === 0 ? (
            <div>Loading Word Cloud...</div>
          ) : (
            <WordCloud tags={tags} onTagClick={setQuery} />
          )}
        </div>
      </div>
      <div className="search-bar">
        <TextInput query={query} setQuery={setQuery} searchFeeds={searchFeeds} />
        <button className="search-button" onClick={searchFeeds}>Search</button>
      </div>
      {noResults ? (
        <h4 className="noResults">No results found.</h4>
      ) : null}
      <Search articles={articles} loading={loading} />
    </div>
  );
}

export default App;
