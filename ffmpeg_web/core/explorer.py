import os
import glob
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import sys

from . import reformat

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
    width: Optional[int] = None
    height: Optional[int] = None

def get_directory_contents(path: str = None) -> BrowseResponse:
    """List contents of a directory."""
    if not path or path == "undefined" or path == "null":
        path = os.getcwd()
    
    # Handle home shortcut
    path = os.path.expanduser(path)
    
    if not os.path.exists(path):
        # Fallback to root or cwd if invalid
        path = os.getcwd()

    # A frame path is a legitimate thing to arrive here: the input field
    # accepts a pasted frame, and older settings files may have persisted one
    # as last_input_folder. Browse the containing folder rather than letting
    # os.scandir raise NotADirectoryError and 500 the whole file browser.
    if os.path.isfile(path):
        path = os.path.dirname(path)

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
    """Find file sequences for a folder, or for a single frame within one.

    Accepts either a directory or the path of one frame. Picking a frame is
    how most people think about choosing a sequence, so a file resolves to
    its folder and the sequence that frame belongs to is returned first --
    which is also the one the UI reads and probes.
    """
    if not clique:
        return []

    try:
        # A single frame identifies both the folder to scan and which of the
        # sequences in it the user actually meant.
        target_file = None
        if os.path.isfile(folder_path):
            target_file = os.path.basename(folder_path)
            folder_path = os.path.dirname(folder_path)

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
        _first_frames: List[str] = []
        target_index = None
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
            if target_file is not None and any(
                os.path.basename(member) == target_file for member in col
            ):
                target_index = len(sequence_items)

            sequence_items.append(item)
            _first_frames.append(
                os.path.join(dir_head, f"{base_head}{start:0{padding}d}{col.tail}")
            )
            
        # Put the sequence the selected frame belongs to first, so it is the
        # one the UI adopts and the one probed below.
        if target_index:
            sequence_items.insert(0, sequence_items.pop(target_index))
            _first_frames.insert(0, _first_frames.pop(target_index))

        # Probe ONLY the sequence the UI actually uses (the first one).
        # Probing every sequence spawned one oiiotool per collection inside
        # this request, which stalls badly on folders holding many
        # sequences. One header-only read is cheap; N of them is not.
        if sequence_items:
            source_size = reformat.probe_resolution(_first_frames[0])
            if source_size:
                sequence_items[0].width = source_size[0]
                sequence_items[0].height = source_size[1]

        return sequence_items
        
    except Exception as e:
        print(f"Error scanning for sequences: {e}")
        return []
