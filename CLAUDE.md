
Git commits use conventional-style

## Performance Guidelines
- Batch multiple file operations into a single tool call where possible.
- Use efficient approaches to minimize tool call repetition.

## Error Handling
- If you encounter an 'unknown' error, verify the tool name and arguments before retrying. Use available documentation or schema to confirm correctness.
- For 'user_prompt' errors, ensure you have explicit permission and the prompt is clear. Avoid redundant prompts; prefer gathering all necessary input at once.


## Efficiency Guidelines

- **Batch tool calls:** When performing multiple operations that can be done in parallel (e.g., reading multiple files, making multiple API calls), batch them into a single tool call or use the most efficient approach to minimize round-trips.
- **Avoid redundant operations:** Cache results where possible.

## Error Handling

- **Prevent unknown errors:** Always validate input parameters and ensure all required fields are provided before making tool calls. Use defensive programming to avoid unexpected states.
- **Avoid user_prompt errors:** When constructing prompts or user-facing messages, ensure all variables are properly formatted and no template placeholders remain unsubstituted.

## Efficiency

- **Batch tool calls**: When performing multiple similar operations (e.g., reading files, searching code), batch them into a single tool call if possible to reduce round-trips.
- **Avoid rapid repeated calls**: If you find yourself calling the same tool rapidly in a loop, consider aggregating the requests or using a more efficient approach like reading a directory listing once and processing in memory.

## Error Prevention & Efficiency

- **Unknown errors**: If you receive an error that is not clearly described, immediately re-read the command or input that caused it and try a slightly different approach (e.g., full paths, explicit flags) before retrying. If the error persists, ask the user for clarification.
- **user_prompt errors**: Always validate the user_prompt for completeness and correct syntax before using it. If the prompt appears malformed, request the user to rephrase or provide more context.
- **Tool call batching**: Prefer combining multiple related tool calls into a single operation (e.g., batch file reads/writes, list then process in one command) to reduce overhead. Avoid sequential calls when a single, more powerful command can accomplish the same task.

## Efficiency Guidelines

- **Batch tool calls** when possible (e.g., combine multiple reads/writes into one `batch` or use `description` parameter to execute multiple steps at once).
- **Avoid redundant tool calls** – check current state before making a call that may have been made already.
- **Prefer bulk operations** (e.g., one `Bash` command that does multiple things) over multiple sequential calls.


## Accuracy Rules

- **Always verify tool names** before calling – check the available tools list (e.g., `list_tools` or `tasks/list_tools`) to ensure the tool exists.
- **Never call a tool with a misspelled or unknown name.** If unsure, use `list_tools` first.
- **For user_prompt errors:** The `user_prompt` parameter is NOT a valid parameter for any tool. Do not include it. Instead, use the tool's documented parameters (e.g., `prompt` or `input`).

## TEST SECTION - REMOVE ME
## TEST SECTION - REMOVE ME