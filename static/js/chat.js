let currentChatCase = null;
let chatHistory = [];

function openCaseChat(index) {
    event.stopPropagation();
    const result = currentResults[index];
    currentChatCase = result;
    
    const caseData = result.data || {};
    const animal = caseData.animal_details || {};
    const report = caseData.report_metadata || {};
    
    // Update case ID and metadata
    document.getElementById('chatCaseId').textContent = result.case_id;
    document.getElementById('chatCaseMeta').innerHTML = `
        <span class="meta-item"><i class="fas fa-file-medical"></i> ${report.report_type || 'Unknown Type'}</span>
        <span class="meta-item"><i class="fas fa-calendar"></i> ${formatDate(report.date_received)}</span>
        <span class="meta-item"><i class="fas fa-user-md"></i> ${(report.pathologists || []).join(', ') || 'Unknown'}</span>
    `;
    
    // Set up context panel
    document.getElementById('chatContext').innerHTML = `
        <div class="context-section">
            <div class="context-header">
                <i class="fas fa-clipboard-list"></i> Case Summary
            </div>
            <div class="context-details summary-text">
                ${caseData.summary || 'No summary available'}
            </div>
        </div>
        <div class="context-section">
            <div class="context-header">
                <i class="fas fa-paw"></i> Patient Information
            </div>
            <div class="context-details">
                <span class="detail-tag"><strong>Species:</strong> ${animal.species || 'Unknown'}</span>
                <span class="detail-tag"><strong>Breed:</strong> ${animal.breed || 'Unknown'}</span>
                <span class="detail-tag"><strong>Age:</strong> ${animal.age || 'Unknown'}</span>
                <span class="detail-tag"><strong>Sex:</strong> ${animal.sex || 'Unknown'}</span>
            </div>
        </div>
    `;
    
    // Initialize chat with AI greeting
    document.getElementById('chatMessages').innerHTML = `
        <div class="chat-message ai">
            <div class="message-avatar">
                <i class="fas fa-robot"></i>
            </div>
            <div class="message-bubble">
                <div class="message-header">
                    Pathology Assistant
                </div>
                <div class="message-content">
                    Hello! I'm a vet pathology assistant for case ${result.case_id}. I have access to all case details including:
                    <ul>
                        <li>Clinical history and presentation</li>
                        <li>Diagnostic findings and test results</li>
                        <li>Pathology reports and interpretations</li>
                    </ul>
                    How can I help you understand this case better?
                </div>
            </div>
        </div>
    `;
    
    document.getElementById('chatModal').style.display = 'block';
}

function insertSuggestion(text) {
    const input = document.getElementById('chatInput');
    input.value = text;
    input.focus();
}

function closeChatModal() {
    document.getElementById('chatModal').style.display = 'none';
    currentChatCase = null;
    chatHistory = [];
}

function clearChat() {
    // Clear the chat messages div except for the initial AI greeting
    const messagesDiv = document.getElementById('chatMessages');
    const initialGreeting = messagesDiv.firstElementChild;
    messagesDiv.innerHTML = '';
    messagesDiv.appendChild(initialGreeting);
    
    // Reset chat history
    chatHistory = [];
    
    // Clear the input
    document.getElementById('chatInput').value = '';
}

async function sendChatMessage() {
    const input = document.getElementById('chatInput');
    const message = input.value.trim();
    
    if (!message || !currentChatCase) return;
    
    // Add user message to chat and history
    const messagesDiv = document.getElementById('chatMessages');
    const userMessage = {
        role: 'user',
        content: message
    };
    chatHistory.push(userMessage);
    
    messagesDiv.innerHTML += `
        <div class="chat-message user">
            <div class="message-avatar">
                <i class="fas fa-user"></i>
            </div>
            <div class="message-bubble">
                <div class="message-header">You</div>
                <div class="message-content">${parseMarkdown(message)}</div>
            </div>
        </div>
    `;
    
    input.value = '';
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    
    // Create AI message container with avatar structure
    const aiMessageDiv = document.createElement('div');
    aiMessageDiv.className = 'chat-message ai';
    aiMessageDiv.innerHTML = `
        <div class="message-avatar">
            <i class="fas fa-robot"></i>
        </div>
        <div class="message-bubble">
            <div class="message-header">Pathology Assistant</div>
            <div class="message-content"></div>
        </div>
    `;
    messagesDiv.appendChild(aiMessageDiv);
    const aiContentDiv = aiMessageDiv.querySelector('.message-content');

    // Add loading spinner
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'loading-spinner';
    loadingDiv.innerHTML = `
        <div class="spinner"></div>
        <span>Analyzing case...</span>
    `;
    messagesDiv.appendChild(loadingDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                case_id: currentChatCase.case_id,
                message: message,
                history: chatHistory
            })
        });
        
        // Remove loading spinner
        messagesDiv.removeChild(loadingDiv);
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let responseText = '';
        
        while (true) {
            const {value, done} = await reader.read();
            if (done) break;
            
            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(5));
                        
                        if (data.error) {
                            aiContentDiv.innerHTML = `<div class="error">${data.error}</div>`;
                            return;
                        }

                        if (data.token) {
                            responseText += data.token;
                            aiContentDiv.innerHTML = parseMarkdown(responseText);
                            messagesDiv.scrollTop = messagesDiv.scrollHeight;
                        }
                    } catch (e) {
                        console.error('Error parsing SSE data:', e);
                    }
                }
            }
        }
        
        // Add completed message to history
        chatHistory.push({
            role: 'assistant',
            content: responseText
        });
        
    } catch (error) {
        console.error('Chat error:', error);
        aiContentDiv.innerHTML = `
            <div class="error">
                Sorry, there was an error processing your request.
            </div>
        `;
    }
}

// Add keyboard handler for chat input
document.addEventListener('DOMContentLoaded', function() {
    const chatInput = document.getElementById('chatInput');
    chatInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendChatMessage();
        }
    });
});
