import os
import glob
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import sys

# Try to import clique, but handle if it's not present (though it should be via Rez)
try:
    import clique
except ImportError:
    clique = None

class FileItem(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: Optional[int] = None
    extension: Optional[str] = None

class BrowseResponse(BaseModel):
    current_path: str
    parent_path: str
    items: List[FileItem]

class SequenceItem(BaseModel):
    head: str
    tail: str
    padding: int
    start: int
    end: int
    count: int
    pattern: str
    range_string: str

def get_directory_contents(path: str = None) -> BrowseResponse:
    """List contents of a directory."""
    if not path or path == "undefined" or path == "null":
        path = os.getcwd()
    
    # Handle home shortcut
    path = os.path.expanduser(path)
    
    if not os.path.exists(path):
        # Fallback to root or cwd if invalid
        path = os.getcwd()

    items = []
    
    try:
        # Get parent directory
        parent_path = os.path.dirname(path)
        
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    is_dir = entry.is_dir()
                    # Filter for relevant files if not a directory
                    if not is_dir:
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext not in ['.png', '.jpg', '.jpeg', '.exr', '.mov', '.mp4', '.tiff']:
                            continue
                            
                    item = FileItem(
                        name=entry.name,
                        path=entry.path,
                        is_dir=is_dir,
                        size=entry.stat().st_size if not is_dir else None,
                        extension=os.path.splitext(entry.name)[1].lower() if not is_dir else None
                    )
                    items.append(item)
                except OSError:
                    continue
                    
        # Sort: directories first, then files
        items.sort(key=lambda x: (not x.is_dir, x.name.lower()))
        
    except PermissionError:
        pass  # Just return empty if no permission

    return BrowseResponse(
        current_path=path,
        parent_path=parent_path,
        items=items
    )

def scan_for_sequences(folder_path: str) -> List[SequenceItem]:
    """Use clique to find file sequences in a folder."""
    if not clique:
        return []

    try:
        # Gather all files
        search_pattern = os.path.join(folder_path, "*")
        files = glob.glob(search_pattern)

        # Filter for images
        image_files = [
            f
            for f in files
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".exr"))
        ]

        # Assemble sequences
        collections, remainder = clique.assemble(image_files)

        sequence_items: List[SequenceItem] = []
        for col in collections:
            indexes = list(col.indexes)
            if not indexes:
                continue

            start = min(indexes)
            end = max(indexes)

            # Reconstruct pattern: head + %0Xd + tail
            # Clique gives us full paths in head/tail; the web UI and
            # ffmpeg handler expect patterns relative to the selected
            # input folder (filename only), so we strip the directory
            # portion here.
            padding = col.padding
            dir_head = os.path.dirname(col.head)
            base_head = os.path.basename(col.head)

            pattern = f"{base_head}%0{padding}d{col.tail}"

            item = SequenceItem(
                head=base_head,
                tail=col.tail,
                padding=padding,
                start=start,
                end=end,
                count=len(indexes),
                pattern=pattern,
                range_string=f"[{start}-{end}]",
            )
            sequence_items.append(item)
            
        return sequence_items
        
    except Exception as e:
        print(f"Error scanning for sequences: {e}")
        return []
