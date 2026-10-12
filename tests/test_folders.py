"""Phase 4：資料夾管理功能測試。

測試資料夾的基本 CRUD 操作。
"""

import pytest
from shop.errors import ConflictError, NotFoundError, ValidationError
from shop.repo import Repository


class TestFolderCRUD:
    """資料夾建立、讀取、更新、刪除。"""

    def test_create_folder_basic(self, repo: Repository):
        """建立基本資料夾。"""
        folder = repo.create_folder("旅遊照片", "度假時拍的照片")
        
        assert folder.id
        assert folder.name == "旅遊照片"
        assert folder.description == "度假時拍的照片"
        assert folder.status == "active"

    def test_create_folder_without_description(self, repo: Repository):
        """建立資料夾（無描述）。"""
        folder = repo.create_folder("工作文件")
        
        assert folder.name == "工作文件"
        assert folder.description is None

    def test_create_folder_duplicate_name(self, repo: Repository):
        """建立同名資料夾應失敗。"""
        repo.create_folder("重複名稱")
        
        with pytest.raises(ConflictError, match="資料夾名稱已存在"):
            repo.create_folder("重複名稱")

    def test_create_folder_empty_name(self, repo: Repository):
        """建立空名稱資料夾應失敗。"""
        with pytest.raises(ValidationError, match="folders.name"):
            repo.create_folder("")

    def test_list_folders(self, repo: Repository):
        """列出資料夾。"""
        repo.create_folder("資料夾A")
        repo.create_folder("資料夾B")
        repo.create_folder("資料夾C")
        
        folders = repo.list_folders()
        
        assert len(folders) == 3
        assert all(f["status"] == "active" for f in folders)
        assert all("item_count" in f for f in folders)

    def test_get_folder(self, repo: Repository):
        """取得單一資料夾。"""
        created = repo.create_folder("特定資料夾")
        
        retrieved = repo.get_folder(created.id)
        
        assert retrieved.id == created.id
        assert retrieved.name == "特定資料夾"

    def test_get_folder_not_found(self, repo: Repository):
        """取得不存在的資料夾應失敗。"""
        with pytest.raises(NotFoundError, match="資料夾不存在"):
            repo.get_folder("nonexistent-id")

    def test_update_folder_name(self, repo: Repository):
        """更新資料夾名稱。"""
        folder = repo.create_folder("原始名稱")
        
        updated = repo.update_folder(folder.id, name="新名稱")
        
        assert updated.name == "新名稱"
        assert updated.id == folder.id

    def test_update_folder_description(self, repo: Repository):
        """更新資料夾描述。"""
        folder = repo.create_folder("資料夾", "原描述")
        
        updated = repo.update_folder(folder.id, description="新描述")
        
        assert updated.description == "新描述"

    def test_delete_folder_empty(self, repo: Repository):
        """刪除空資料夾。"""
        folder = repo.create_folder("空資料夾")
        
        repo.delete_folder(folder.id)
        
        with pytest.raises(NotFoundError):
            repo.get_folder(folder.id)

    def test_get_unclassified_items(self, repo: Repository):
        """取得未分類的紀錄。"""
        unclass1 = repo.create_item(name="未分類1")
        unclass2 = repo.create_item(name="未分類2")
        
        items, count = repo.get_unclassified_items()
        
        # 至少應該包含我們創建的未分類項目
        assert count >= 2
        assert any(i.id == unclass1.id for i in items)
        assert any(i.id == unclass2.id for i in items)
