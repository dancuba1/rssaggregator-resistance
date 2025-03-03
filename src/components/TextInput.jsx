


export function TextInput({query, setQuery, searchFeeds}){
    const handleKeyDown = (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          searchFeeds();
          console.log("found searchfeeds") // Call the function when Enter is pressed
        }
      };
    return(<div className="search-input">
        <input
            className="text-search"
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)} // Update query on input
            onKeyDown={handleKeyDown} // Add keydown event
            placeholder="Search tags (e.g., art,history -modern)"
          />
      </div>);}

