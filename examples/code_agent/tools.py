"""Code analysis tools with vizpath tracing.

These tools operate on real local files, not mocks.
"""

from pathlib import Path
from typing import Any

from vizpath import tracer


@tracer.tool(name="search_files")
def search_files(pattern: str, directory: str = ".") -> list[dict[str, Any]]:
    """Search for files matching a glob pattern.

    Args:
        pattern: Glob pattern (e.g., "*.py", "**/*.ts", "src/**/*.py")
        directory: Directory to search in (default: current directory)

    Returns:
        List of matching files with path, name, and size
    """
    results = []
    base_path = Path(directory).resolve()

    # Skip hidden directories and common non-code directories
    skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"}

    try:
        for path in base_path.rglob(pattern):
            # Skip if any parent directory is in skip list
            if any(part in skip_dirs for part in path.parts):
                continue

            if path.is_file():
                try:
                    results.append({
                        "path": str(path.relative_to(base_path)),
                        "name": path.name,
                        "size": path.stat().st_size,
                    })
                except (OSError, ValueError):
                    continue

        # Sort by path and limit results
        results.sort(key=lambda x: x["path"])
        results = results[:50]  # Limit to 50 files

        tracer.set_span_attributes({
            "search.pattern": pattern,
            "search.directory": str(base_path),
            "search.result_count": len(results),
        })

    except Exception as e:
        tracer.set_span_attributes({
            "search.error": str(e),
        })
        return [{"error": str(e)}]

    return results


@tracer.tool(name="read_file")
def read_file(path: str, max_lines: int = 200) -> dict[str, Any]:
    """Read contents of a file.

    Args:
        path: Path to the file to read
        max_lines: Maximum number of lines to read (default: 200)

    Returns:
        Dictionary with file path, content, and line count
    """
    p = Path(path)

    # Try to resolve relative to common directories
    if not p.exists():
        for base in [".", "vizpath", "server", "sdk", "dashboard"]:
            candidate = Path(base) / path
            if candidate.exists():
                p = candidate
                break

    if not p.exists():
        tracer.set_span_attributes({
            "file.path": path,
            "file.error": "not_found",
        })
        return {"error": f"File not found: {path}"}

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")
        total_lines = len(lines)

        # Truncate if too long
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            content = "\n".join(lines)
            content += f"\n\n... (truncated, showing {max_lines} of {total_lines} lines)"

        tracer.set_span_attributes({
            "file.path": str(p),
            "file.lines": total_lines,
            "file.lines_returned": len(lines),
            "file.size": p.stat().st_size,
        })

        return {
            "path": str(p),
            "content": content,
            "lines": total_lines,
        }

    except Exception as e:
        tracer.set_span_attributes({
            "file.path": path,
            "file.error": str(e),
        })
        return {"error": f"Error reading file: {e}"}


@tracer.tool(name="list_directory")
def list_directory(path: str = ".") -> list[dict[str, Any]]:
    """List contents of a directory.

    Args:
        path: Directory path (default: current directory)

    Returns:
        List of items with name, type (file/dir), and size
    """
    p = Path(path)

    if not p.exists():
        tracer.set_span_attributes({
            "dir.path": path,
            "dir.error": "not_found",
        })
        return [{"error": f"Directory not found: {path}"}]

    if not p.is_dir():
        tracer.set_span_attributes({
            "dir.path": path,
            "dir.error": "not_a_directory",
        })
        return [{"error": f"Not a directory: {path}"}]

    items = []
    skip_items = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}

    try:
        for item in sorted(p.iterdir()):
            if item.name.startswith(".") and item.name not in [".env.example"]:
                continue
            if item.name in skip_items:
                continue

            entry = {
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
            }

            if item.is_file():
                try:
                    entry["size"] = item.stat().st_size
                except OSError:
                    entry["size"] = 0

            items.append(entry)

        tracer.set_span_attributes({
            "dir.path": str(p),
            "dir.item_count": len(items),
        })

    except Exception as e:
        tracer.set_span_attributes({
            "dir.error": str(e),
        })
        return [{"error": str(e)}]

    return items


@tracer.tool(name="analyze_code")
def analyze_code(file_path: str) -> dict[str, Any]:
    """Analyze a code file for structure and patterns.

    Args:
        file_path: Path to the code file to analyze

    Returns:
        Dictionary with code analysis results
    """
    result = read_file(file_path, max_lines=500)

    if "error" in result:
        return result

    content = result["content"]
    lines = content.split("\n")

    # Basic code analysis
    analysis = {
        "path": file_path,
        "total_lines": len(lines),
        "blank_lines": sum(1 for line in lines if not line.strip()),
        "comment_lines": 0,
        "imports": [],
        "functions": [],
        "classes": [],
    }

    # Detect language and analyze accordingly
    ext = Path(file_path).suffix.lower()

    if ext == ".py":
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#"):
                analysis["comment_lines"] += 1
            elif stripped.startswith(("import ", "from ")):
                analysis["imports"].append(stripped)
            elif stripped.startswith("def "):
                # Extract function name
                name = stripped[4:].split("(")[0].strip()
                analysis["functions"].append({"name": name, "line": i + 1})
            elif stripped.startswith("class "):
                # Extract class name
                name = stripped[6:].split("(")[0].split(":")[0].strip()
                analysis["classes"].append({"name": name, "line": i + 1})

    elif ext in [".ts", ".tsx", ".js", ".jsx"]:
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("//"):
                analysis["comment_lines"] += 1
            elif stripped.startswith("import "):
                analysis["imports"].append(stripped)
            elif "function " in stripped or stripped.startswith("const ") and "=>" in stripped:
                # Simple function detection
                if "function " in stripped:
                    parts = stripped.split("function ")
                    if len(parts) > 1:
                        name = parts[1].split("(")[0].strip()
                        if name:
                            analysis["functions"].append({"name": name, "line": i + 1})
            elif stripped.startswith(("class ", "export class ")):
                name = stripped.replace("export ", "").replace("class ", "").split(" ")[0].split("{")[0].strip()
                if name:
                    analysis["classes"].append({"name": name, "line": i + 1})

    # Limit arrays to avoid huge outputs
    analysis["imports"] = analysis["imports"][:20]
    analysis["functions"] = analysis["functions"][:30]
    analysis["classes"] = analysis["classes"][:20]

    tracer.set_span_attributes({
        "analysis.path": file_path,
        "analysis.lines": analysis["total_lines"],
        "analysis.functions": len(analysis["functions"]),
        "analysis.classes": len(analysis["classes"]),
    })

    return analysis


# Tool definitions for the LLM
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for files matching a glob pattern. Use patterns like '*.py' for Python files, '**/*.ts' for TypeScript files recursively, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern to match files (e.g., '*.py', 'src/**/*.ts', '**/test_*.py')",
                    },
                    "directory": {
                        "type": "string",
                        "description": "Directory to search in (default: current directory)",
                        "default": ".",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. Returns the file content, path, and line count.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to read",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "Maximum lines to read (default: 200)",
                        "default": 200,
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List the contents of a directory. Shows files and subdirectories with their types.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list (default: current directory)",
                        "default": ".",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_code",
            "description": "Analyze a code file for structure: imports, functions, classes, and line counts. Works with Python, TypeScript, and JavaScript files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the code file to analyze",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_analysis",
            "description": "Signal that you have gathered enough information and are ready to provide your final answer. Call this when you can answer the user's question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of what you found",
                    },
                },
                "required": ["summary"],
            },
        },
    },
]
