// Simple markdown parser
function parseMarkdown(text) {
    if (!text) return '';

    // Handle code blocks first
    text = text.replace(/```([^`]+)```/g, '<pre><code>$1</code></pre>');

    // Handle inline code
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Handle bold
    text = text.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');

    // Handle italic - but not list items
    text = text.replace(/(?<![-\s])\*([^*\n]+)\*/g, '<em>$1</em>');

    // Handle headers
    text = text.replace(/^### (.*$)/gm, '<h3>$1</h3>');
    text = text.replace(/^## (.*$)/gm, '<h2>$1</h2>');
    text = text.replace(/^# (.*$)/gm, '<h1>$1</h1>');

    // Split into lines and process
    const lines = text.split('\n');
    let result = [];
    let inList = false;
    let listType = null;

    for (let i = 0; i < lines.length; i++) {
        let line = lines[i];

        // Check for bullet list item
        const bulletMatch = line.match(/^[\s]*[-*][\s]+(.+)$/);
        // Check for numbered list item
        const numberMatch = line.match(/^[\s]*\d+\.[\s]+(.+)$/);

        if (bulletMatch) {
            if (!inList || listType !== 'ul') {
                if (inList) result.push(listType === 'ol' ? '</ol>' : '</ul>');
                result.push('<ul>');
                inList = true;
                listType = 'ul';
            }
            result.push('<li>' + bulletMatch[1] + '</li>');
        } else if (numberMatch) {
            if (!inList || listType !== 'ol') {
                if (inList) result.push(listType === 'ol' ? '</ol>' : '</ul>');
                result.push('<ol>');
                inList = true;
                listType = 'ol';
            }
            result.push('<li>' + numberMatch[1] + '</li>');
        } else {
            // Close list if we were in one
            if (inList) {
                result.push(listType === 'ol' ? '</ol>' : '</ul>');
                inList = false;
                listType = null;
            }
            // Add non-list content
            if (line.trim()) {
                result.push(line);
            } else if (result.length > 0) {
                result.push('<br>');
            }
        }
    }

    // Close any open list
    if (inList) {
        result.push(listType === 'ol' ? '</ol>' : '</ul>');
    }

    return result.join('\n');
}
