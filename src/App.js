import React, { useEffect, useState } from "react";
import "./App.css";
import { TextInput } from "./components/TextInput";
import { Search } from "./components/Search";
import { WordCloud } from "./components/WordCloud";


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
        //const response = await fetch("http://127.0.0.1:5000/count_tags");
        if (!response.ok) {
          const errorText = await response.text();
          setError("Failed to fetch tags: " + errorText);
          console.error("API Error:", errorText);
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
      //const response = await fetch(`http://127.0.0.1:5000/search?query=${encodeURIComponent(query)}`);
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
      <div className="word-cloud-container">
        <div className="word-cloud">
          {tags.length === 0 ? (
            <div className="loading-wc"></div>
          ) : (
            <WordCloud tags={tags} onTagClick={setQuery} />
          )}
        </div>
      </div>
      <div className="search-bar">
        <TextInput className="search-input" query={query} setQuery={setQuery} searchFeeds={searchFeeds} />
        <button className="search-button" onClick={searchFeeds}>
          <img className="search-svg" src="/wp-content/uploads/search.svg" alt="Search" />

        </button>
      </div>
      {noResults ? (
        <h4 className="noResults">No results found.</h4>
      ) : null}
      <Search articles={articles} loading={loading} />
    </div>
  );
}

export default App;
