#!/usr/bin/env python
"""
Script to compile .po files to .mo files using polib library.
This works without requiring gettext tools.
"""

import polib
from pathlib import Path

def compile_po_files():
    """Compile all .po files to .mo files."""
    locale_dir = Path('locale')
    
    if not locale_dir.exists():
        print("Locale directory not found!")
        return
    
    po_files = list(locale_dir.rglob('*.po'))
    
    if not po_files:
        print("No .po files found!")
        return
    
    for po_file in po_files:
        print(f"Processing {po_file}...")
        
        try:
            # Parse the .po file
            po = polib.pofile(str(po_file))
            
            # Create .mo file path
            mo_file = po_file.with_suffix('.mo')
            
            # Save as .mo file
            po.save_as_mofile(str(mo_file))
            
            print(f"Created {mo_file}")
            
        except Exception as e:
            print(f"Error processing {po_file}: {e}")

if __name__ == '__main__':
    compile_po_files() 