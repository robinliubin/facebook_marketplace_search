# facebook_marketplace_search
## what it does:
 1. user should be able to input a string as search keywords, following facebook market place search filters
	i.e gants hockey 11", new, 10km distance, price between 50-100, listed in 1 week
 2. then this engine should set these filters and launch the search, and store results in temp database, i.e sqlite
 3. whenever user launch the search, this tool should compare the search result with existing items in database, and double validate the filters
 4. why the current facebook marketplace search does not work, is when user asking for size 11, the search will return bunch size 7 or 14, 15, I dont want to waste my time on clicking them
