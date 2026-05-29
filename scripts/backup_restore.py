#!/usr/bin/env python3
"""
VetPathDB Production Backup & Restore Script
Backs up both MongoDB and ChromaDB production databases safely.
"""

import subprocess
import os
import sys
import logging
import argparse
import shutil
from datetime import datetime
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

class VetPathDBBackup:
    def __init__(self, backup_dir="./backups"):
        self.backup_dir = Path(backup_dir)
        self.mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
        self.prod_db = "cases"
        self.vector_store_path = "./cases_vectorstore"
        
        # Create backup directory
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
    def create_backup(self, backup_name=None):
        """Create a complete backup of production data"""
        
        if not backup_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"vetpathdb_backup_{timestamp}"
        
        backup_path = self.backup_dir / backup_name
        
        logger.info(f"=== Creating Production Backup: {backup_name} ===")
        logger.info(f"Backup location: {backup_path}")
        
        try:
            # Create backup directory
            backup_path.mkdir(parents=True, exist_ok=True)
            
            # 1. Backup MongoDB
            logger.info("Step 1/2: Backing up MongoDB...")
            mongo_backup_path = backup_path / "mongodb"
            
            cmd = [
                "mongodump",
                "--uri", self.mongo_uri,
                "--db", self.prod_db,
                "--out", str(mongo_backup_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"MongoDB backup failed: {result.stderr}")
                return False
            
            logger.info(f"✓ MongoDB backup completed: {mongo_backup_path}")
            
            # 2. Backup ChromaDB vector store
            logger.info("Step 2/2: Backing up ChromaDB vector store...")
            
            if os.path.exists(self.vector_store_path):
                vector_backup_path = backup_path / "chromadb"
                shutil.copytree(self.vector_store_path, vector_backup_path)
                logger.info(f"✓ ChromaDB backup completed: {vector_backup_path}")
            else:
                logger.warning(f"Vector store not found: {self.vector_store_path}")
            
            # Create backup info file
            info_file = backup_path / "backup_info.txt"
            with open(info_file, 'w') as f:
                f.write(f"VetPathDB Production Backup\n")
                f.write(f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"MongoDB Database: {self.prod_db}\n")
                f.write(f"Vector Store: {self.vector_store_path}\n")
                f.write(f"Backup Size: {self._get_dir_size(backup_path):.1f} MB\n")
            
            total_size = self._get_dir_size(backup_path)
            logger.info(f"✓ Backup completed successfully!")
            logger.info(f"Total backup size: {total_size:.1f} MB")
            logger.info(f"Backup location: {backup_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"Backup failed: {str(e)}")
            return False
    
    def restore_backup(self, backup_name, confirm=True):
        """Restore production data from backup"""
        
        backup_path = self.backup_dir / backup_name
        
        if not backup_path.exists():
            logger.error(f"Backup not found: {backup_path}")
            return False
        
        # Safety check
        if confirm:
            logger.warning("=== PRODUCTION RESTORE WARNING ===")
            logger.warning(f"This will COMPLETELY REPLACE production data with backup: {backup_name}")
            logger.warning(f"Current production database '{self.prod_db}' will be DELETED!")
            logger.warning(f"Current vector store '{self.vector_store_path}' will be DELETED!")
            confirm_input = input("Type 'RESTORE' to confirm: ")
            if confirm_input != "RESTORE":
                logger.info("Restore cancelled.")
                return False
        
        logger.info(f"=== Restoring Production from Backup: {backup_name} ===")
        
        try:
            # 1. Restore MongoDB
            mongo_backup_path = backup_path / "mongodb" / self.prod_db
            if mongo_backup_path.exists():
                logger.info("Step 1/2: Restoring MongoDB...")
                
                # Drop existing database first
                from pymongo import MongoClient
                client = MongoClient(self.mongo_uri)
                client.drop_database(self.prod_db)
                logger.info(f"Dropped existing database: {self.prod_db}")
                client.close()
                
                # Restore from backup
                cmd = [
                    "mongorestore",
                    "--uri", self.mongo_uri,
                    "--db", self.prod_db,
                    str(mongo_backup_path)
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    logger.error(f"MongoDB restore failed: {result.stderr}")
                    return False
                
                logger.info("✓ MongoDB restore completed")
            else:
                logger.warning(f"MongoDB backup not found in: {mongo_backup_path}")
            
            # 2. Restore ChromaDB vector store
            vector_backup_path = backup_path / "chromadb"
            if vector_backup_path.exists():
                logger.info("Step 2/2: Restoring ChromaDB vector store...")
                
                # Remove existing vector store
                if os.path.exists(self.vector_store_path):
                    shutil.rmtree(self.vector_store_path)
                    logger.info(f"Removed existing vector store: {self.vector_store_path}")
                
                # Restore from backup
                shutil.copytree(vector_backup_path, self.vector_store_path)
                logger.info(f"✓ ChromaDB restore completed: {self.vector_store_path}")
            else:
                logger.warning(f"ChromaDB backup not found in: {vector_backup_path}")
            
            logger.info("✓ Restore completed successfully!")
            return True
            
        except Exception as e:
            logger.error(f"Restore failed: {str(e)}")
            return False
    
    def list_backups(self):
        """List all available backups"""
        logger.info("=== Available Backups ===")
        
        if not self.backup_dir.exists():
            logger.info("No backups found.")
            return
        
        backups = []
        for item in self.backup_dir.iterdir():
            if item.is_dir() and item.name.startswith("vetpathdb_backup_"):
                info_file = item / "backup_info.txt"
                size = self._get_dir_size(item)
                
                if info_file.exists():
                    with open(info_file, 'r') as f:
                        lines = f.readlines()
                        created = "Unknown"
                        for line in lines:
                            if line.startswith("Created:"):
                                created = line.split("Created:")[1].strip()
                                break
                else:
                    created = "Unknown"
                
                backups.append({
                    'name': item.name,
                    'created': created,
                    'size': size,
                    'path': item
                })
        
        if not backups:
            logger.info("No backups found.")
            return
        
        # Sort by creation time
        backups.sort(key=lambda x: x['name'], reverse=True)
        
        logger.info(f"Found {len(backups)} backup(s):")
        for backup in backups:
            logger.info(f"  {backup['name']}")
            logger.info(f"    Created: {backup['created']}")
            logger.info(f"    Size: {backup['size']:.1f} MB")
            logger.info(f"    Path: {backup['path']}")
            logger.info("")
    
    def delete_backup(self, backup_name):
        """Delete a backup"""
        backup_path = self.backup_dir / backup_name
        
        if not backup_path.exists():
            logger.error(f"Backup not found: {backup_name}")
            return False
        
        try:
            shutil.rmtree(backup_path)
            logger.info(f"✓ Deleted backup: {backup_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete backup: {str(e)}")
            return False
    
    def _get_dir_size(self, path):
        """Get directory size in MB"""
        total = 0
        for root, dirs, files in os.walk(path):
            for file in files:
                total += os.path.getsize(os.path.join(root, file))
        return total / (1024 * 1024)  # Convert to MB

def main():
    parser = argparse.ArgumentParser(description='VetPathDB Production Backup & Restore')
    parser.add_argument('action', choices=['backup', 'restore', 'list', 'delete'],
                       help='Action to perform')
    parser.add_argument('--name', help='Backup name (for restore/delete operations)')
    parser.add_argument('--backup-dir', default='./backups',
                       help='Backup directory (default: ./backups)')
    parser.add_argument('--force', action='store_true',
                       help='Skip confirmation prompts')
    
    args = parser.parse_args()
    
    backup_manager = VetPathDBBackup(args.backup_dir)
    
    if args.action == 'backup':
        success = backup_manager.create_backup(args.name)
        sys.exit(0 if success else 1)
        
    elif args.action == 'restore':
        if not args.name:
            logger.error("--name required for restore operation")
            sys.exit(1)
        success = backup_manager.restore_backup(args.name, confirm=not args.force)
        sys.exit(0 if success else 1)
        
    elif args.action == 'list':
        backup_manager.list_backups()
        
    elif args.action == 'delete':
        if not args.name:
            logger.error("--name required for delete operation")
            sys.exit(1)
        success = backup_manager.delete_backup(args.name)
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()