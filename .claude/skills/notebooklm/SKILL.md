---
name: notebooklm
description: Control NotebookLM via browser automation using the Claude Chrome Extension. Use this skill whenever the user wants to interact with any of their NotebookLM notebooks — reading content, pulling summaries or key takeaways, adding sources (URLs, text, files, YouTube links), generating Studio outputs (infographics, slide decks, audio overviews, study guides, briefing docs, mind maps, timelines, FAQs), or creating new notebooks. Triggers on any phrase involving NotebookLM — "open NotebookLM", "check my [notebook name] notebook", "pull info from NotebookLM", "ask my notebook about X", "add [source] to NotebookLM", "create an infographic in NotebookLM", "use NotebookLM Studio", "generate a slide deck from my notebook", "what does my notebook say about X", or any variation where the goal involves NotebookLM. When in doubt, use this skill — don't try to replicate NotebookLM's functionality manually.
---

# NotebookLM Skill

This skill uses browser automation (Claude in Chrome) to control NotebookLM at https://notebooklm.google.com. It handles four main actions: reading/extracting info, adding sources, generating Studio outputs, and creating new notebooks.

## Step 0: Always Start Here

Before doing anything else:

1. Call `tabs_context_mcp` to get a valid tab ID — every browser tool requires one
2. Call `computer` (action: `screenshot`) to see the current state of the browser
3. Decide whether to navigate or work from the current page

If not already on NotebookLM, navigate there:
```
navigate(url: "https://notebooklm.google.com", tabId: <tab_id>)
```

Then screenshot again to confirm the page loaded. If you see a Google login screen, stop and tell the user they need to log in first — do not attempt to handle login yourself.

---

## Finding and Opening a Notebook

The NotebookLM homepage shows notebooks as cards in a grid. To open the right one:

1. Screenshot to see what's on the page
2. Use `find` to locate the notebook: `find("<notebook name> card", tabId)`
3. Click it — use the ref from `find` or click from coordinates in the screenshot

If the user didn't specify which notebook to open and there are multiple, screenshot the homepage and ask them which one before proceeding.

---

## Action: Read / Extract Info

Use the notebook's built-in chat to pull information, answer questions, or extract takeaways.

1. Open the notebook
2. Screenshot — the chat input box is at the bottom center of the page
3. `find("chat input", tabId)` or click directly on the input from the screenshot
4. Type the user's question using `computer` (action: `type`)
5. Press Enter: `computer` (action: `key`, text: `Return`)
6. Wait 3–5 seconds, then screenshot to capture the response
7. Report the answer back in clean, readable form — don't just dump raw chat output

NotebookLM's chat is grounded in the notebook's sources and cites them inline, so the answers are reliable. For broad extraction ("give me all the key points"), ask the question just as you'd phrase it naturally.

---

## Action: Add Sources

Sources can be website URLs, YouTube links, copied text, Google Docs/Drive files, uploaded local files — or synthesized content you generate on the fly.

1. Open the notebook
2. Screenshot — the Sources panel is the left sidebar
3. Click the **"+ Add source"** button (top of the left panel)
4. A dialog appears with source type options. Handle based on what the user wants to add:

   - **URL / website / YouTube**: Select the link option, paste the URL into the input field using `form_input` or `type`
   - **Copied text**: Select "Copied text", click the text area, type or paste the content
   - **File upload**: Use `file_upload` with the file's absolute path and the ref of the file input element — do NOT click the file picker button (it opens a native dialog you can't interact with)
   - **Google Doc**: Select the Google Docs option and follow the Drive picker

5. Confirm / click the upload/add button
6. Wait for processing — NotebookLM shows a spinner while it ingests the source. Use `computer` (action: `wait`, duration: 5), then screenshot to verify it was added successfully

### Synthesizing Content as a Source

Sometimes the user will ask you to *create* content and add it as a source — for example: "turn this conversation into a podcast in NotebookLM" or "research X and add it to my notebook."

In these cases:
1. **Gather or generate the content first** — research it, summarize it, extract it, or write it up based on whatever the user referenced
2. **Add it as "Copied text"** — open the Add Source dialog, select "Copied text", and paste in the synthesized content
3. **Then proceed with whatever action the user asked for** (e.g., generate Audio Overview)

This is a powerful pattern: you're essentially feeding NotebookLM a curated, pre-processed source rather than a raw URL, which often produces better outputs.

---

## Action: Studio Outputs

Studio is NotebookLM's generation feature for creating structured outputs from your notebook's sources. It lives in the right-side panel.

**Available output types:**
- Audio Overview (podcast-style conversation)
- Study Guide (key terms, questions, essay prompts)
- Briefing Doc (executive summary)
- Timeline (chronological events)
- FAQ
- Table of Contents
- Infographic (visual summary — newer feature)
- Slides / Mind Map (newer features, may be under "Discover more")

**Workflow:**

1. Open the notebook
2. Screenshot — look for the Studio panel on the right side. If you don't see it, look for a "Studio" tab button or panel toggle
3. `find` the output button you need: e.g., `find("Infographic button", tabId)` or `find("Audio Overview button", tabId)`
4. **Open the customization menu first** — each Studio button has a small arrow or chevron on its right side that opens a prompt/customization dialog. Click that (not the main button) to open it before generating
5. **Write a detailed custom prompt** in the customization field. Don't leave it blank or use the default — a specific prompt produces dramatically better output. Tailor it based on what the user is trying to achieve. Examples:
   - For Audio Overview: "Create a dynamic, engaging conversation between two hosts who are genuinely excited about this topic. Focus on the most surprising or counterintuitive insights. Use concrete examples, avoid corporate jargon, and make it accessible to a general audience. Keep the energy high throughout."
   - For Infographic: "Highlight the 5–7 most important concepts with clear visual hierarchy. Emphasize comparisons and relationships between ideas. Use a logical flow from top to bottom."
   - For Study Guide: "Focus on practical application. Include real-world scenarios in the questions. Make the key terms section comprehensive with clear definitions."
   - Adapt the prompt based on what the user told you — if they gave specific direction, incorporate it
6. Confirm/submit the custom prompt and click Generate
7. **Do NOT wait for generation** — Studio outputs (especially Audio Overview) take a long time. Once you've clicked Generate and confirmed the generation has started, tell the user it's in progress and that NotebookLM will notify them when it's ready. Then you're done with this step.

**Finding newer Studio features:** If Infographic, Slides, or Mind Map aren't visible in the Studio panel, scroll down or look for a "+" or "Discover more" section — these features were added later and may be tucked away.

---

## Action: Create a New Notebook

1. From the NotebookLM homepage, click "New notebook" or the "+" button
2. A new empty notebook opens
3. Set the title: find and click the title field at the top, then type the name
4. Add sources using the workflow above
5. NotebookLM will auto-generate a summary and notes once sources finish processing

---

## Saving Outputs

When you extract text, pull takeaways, or generate any output the user wants to keep, save it to their workspace folder. Use the `Write` tool to save text outputs as `.md` files. For downloaded files (audio, etc.), they'll land in the browser's default download folder — let the user know where to find them.

---

## General Tips

- **Screenshot constantly** — NotebookLM is a dynamic SPA. The UI can vary by account and feature rollout. When in doubt, screenshot before acting.
- **Use `find` before clicking** — it returns stable element refs that are more reliable than pixel coordinates
- **Wait for processing** — source ingestion and Studio generation are async. Don't assume something is done without a confirming screenshot
- **Chat is your best extraction tool** — for pulling info, it's almost always better to ask the notebook a direct question than to try to scrape the sources panel
- **One action at a time** — do each step, confirm it worked via screenshot, then move to the next

---

## Reporting Back

After completing any action:
1. Take a final screenshot (save_to_disk: true) if there's something visual worth showing
2. Give the user a clear summary: what notebook was used, what was done, what the result was
3. If you extracted information, present it cleanly and formatted — not raw chat dumps
4. If you generated a Studio output, describe what was created and where it is
