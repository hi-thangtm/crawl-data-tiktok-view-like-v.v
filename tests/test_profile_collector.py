import json
import unittest
from pathlib import Path

import openpyxl

from app.models import TikTokProfileResult, VideoResult
from app.utils.url_parser import (
    parse_tiktok_url,
    parse_tiktok_channel_input,
    deduplicate_channel_inputs,
    TikTokChannelInput,
)
from app.collectors.tiktok_profile_http import (
    extract_profile_from_html,
    find_user_info_struct,
    build_profile_result_from_data,
    parse_count_value,
)
from app.utils.profile_excel import export_profile_excel
from run_batch import deduplicate_urls


class TestProfileCollector(unittest.TestCase):

    def test_profile_normal_full(self):
        """Profile bình thường, đầy đủ dữ liệu."""
        html = """
        <html><body><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">
        {
          "__DEFAULT_SCOPE__": {
            "webapp.user-detail": {
              "userInfo": {
                "user": {
                  "id": "7123456789012345678",
                  "secUid": "MS4wLjABAAAAabcdef123456",
                  "uniqueId": "full_creator",
                  "nickname": "Full Creator ✨",
                  "signature": "Dòng 1 bio 🇻🇳\\nDòng 2 bio 🚀",
                  "verified": true,
                  "privateAccount": false,
                  "avatarLarger": "https://example.com/avatar.jpg",
                  "bioLink": {"link": "https://example.com/shop"}
                },
                "statsV2": {
                  "followerCount": 2500000,
                  "followingCount": 150,
                  "heartCount": 50000000,
                  "videoCount": 350
                }
              }
            }
          }
        }
        </script></body></html>
        """
        user_node, s2, s, src = extract_profile_from_html(html)
        self.assertIsNotNone(user_node)
        self.assertEqual(src, "UNIVERSAL_DATA")

        res = build_profile_result_from_data(
            input_url="@full_creator",
            normalized_url="https://www.tiktok.com/@full_creator",
            user_node=user_node,
            stats_v2=s2,
            stats_node=s,
            source_method=f"HTTP/{src}",
            target_username="full_creator",
        )

        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.username, "full_creator")
        self.assertEqual(res.nickname, "Full Creator ✨")
        self.assertEqual(res.user_id, "7123456789012345678")
        self.assertIsInstance(res.user_id, str)
        self.assertEqual(res.sec_uid, "MS4wLjABAAAAabcdef123456")
        self.assertIsInstance(res.sec_uid, str)
        self.assertEqual(res.bio, "Dòng 1 bio 🇻🇳\nDòng 2 bio 🚀")
        self.assertTrue(res.verified)
        self.assertFalse(res.private_account)
        self.assertEqual(res.avatar_url, "https://example.com/avatar.jpg")
        self.assertEqual(res.bio_website_url, "https://example.com/shop")
        self.assertEqual(res.follower_count, 2500000)
        self.assertEqual(res.following_count, 150)
        self.assertEqual(res.likes_count, 50000000)
        self.assertEqual(res.video_count, 350)
        self.assertEqual(res.stats_precision, "exact")

    def test_profile_missing_bio(self):
        """Profile thiếu bio (signature là None hoặc rỗng)."""
        html = """
        <html><body><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">
        {
          "__DEFAULT_SCOPE__": {
            "webapp.user-detail": {
              "userInfo": {
                "user": {
                  "id": "111222333",
                  "uniqueId": "no_bio_user",
                  "nickname": "No Bio"
                },
                "statsV2": {
                  "followerCount": 100
                }
              }
            }
          }
        }
        </script></body></html>
        """
        user_node, s2, s, src = extract_profile_from_html(html)
        res = build_profile_result_from_data(
            "no_bio_user", "https://www.tiktok.com/@no_bio_user", user_node, s2, s, "HTTP/TEST"
        )
        self.assertIsNone(res.bio)
        self.assertEqual(res.status, "SUCCESS")

    def test_profile_no_website(self):
        """Profile không có website (bioLink thiếu)."""
        html = """
        <html><body><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">
        {
          "__DEFAULT_SCOPE__": {
            "webapp.user-detail": {
              "userInfo": {
                "user": {
                  "id": "444555",
                  "uniqueId": "no_web_user",
                  "nickname": "No Web"
                },
                "statsV2": {
                  "followerCount": 500
                }
              }
            }
          }
        }
        </script></body></html>
        """
        user_node, s2, s, src = extract_profile_from_html(html)
        res = build_profile_result_from_data(
            "no_web_user", "https://www.tiktok.com/@no_web_user", user_node, s2, s, "HTTP/TEST"
        )
        self.assertIsNone(res.bio_website_url)

    def test_profile_zero_follower(self):
        """Profile có follower bằng 0 (phải giữ 0, không biến thành None)."""
        html = """
        <html><body><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">
        {
          "__DEFAULT_SCOPE__": {
            "webapp.user-detail": {
              "userInfo": {
                "user": {
                  "id": "888999",
                  "uniqueId": "zero_user"
                },
                "statsV2": {
                  "followerCount": 0,
                  "videoCount": 2
                }
              }
            }
          }
        }
        </script></body></html>
        """
        user_node, s2, s, src = extract_profile_from_html(html)
        res = build_profile_result_from_data(
            "zero_user", "https://www.tiktok.com/@zero_user", user_node, s2, s, "HTTP/TEST"
        )
        self.assertEqual(res.follower_count, 0)
        self.assertIsInstance(res.follower_count, int)

    def test_profile_missing_follower_field(self):
        """Profile không có trường follower (phải là None, KHÔNG được tự động chuyển thành 0)."""
        html = """
        <html><body><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">
        {
          "__DEFAULT_SCOPE__": {
            "webapp.user-detail": {
              "userInfo": {
                "user": {
                  "id": "777888",
                  "uniqueId": "hidden_stats_user"
                },
                "statsV2": {
                  "videoCount": 10
                }
              }
            }
          }
        }
        </script></body></html>
        """
        user_node, s2, s, src = extract_profile_from_html(html)
        res = build_profile_result_from_data(
            "hidden_stats_user", "https://www.tiktok.com/@hidden_stats_user", user_node, s2, s, "HTTP/TEST"
        )
        self.assertIsNone(res.follower_count)
        self.assertNotEqual(res.follower_count, 0)

    def test_profile_with_stats_v2(self):
        """Profile có statsV2 được ưu tiên hơn stats."""
        user = {"id": "1", "uniqueId": "v2_user"}
        stats_v2 = {"followerCount": 1234, "videoCount": 5}
        stats = {"followerCount": 9999, "videoCount": 99}
        res = build_profile_result_from_data(
            "v2_user", "https://www.tiktok.com/@v2_user", user, stats_v2, stats, "TEST"
        )
        self.assertEqual(res.follower_count, 1234)
        self.assertEqual(res.video_count, 5)

    def test_profile_only_stats(self):
        """Profile chỉ có stats (không có statsV2)."""
        user = {"id": "2", "uniqueId": "v1_user"}
        stats = {"followerCount": 5432, "heartCount": 12000, "videoCount": 20}
        res = build_profile_result_from_data(
            "v1_user", "https://www.tiktok.com/@v1_user", user, None, stats, "TEST"
        )
        self.assertEqual(res.follower_count, 5432)
        self.assertEqual(res.likes_count, 12000)
        self.assertEqual(res.video_count, 20)

    def test_profile_not_found(self):
        """Profile không tồn tại (statusCode = 10202 hoặc text không tìm thấy)."""
        html_code = """
        <html><body><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">
        {
          "__DEFAULT_SCOPE__": {
            "webapp.user-detail": {
              "statusCode": 10202
            }
          }
        }
        </script></body></html>
        """
        u, s2, s, src = extract_profile_from_html(html_code)
        self.assertIsNone(u)
        self.assertEqual(src, "NOT_FOUND")

        html_text = "<html><body><div>Không tìm thấy tài khoản này</div></body></html>"
        u2, s2_2, s_2, src2 = extract_profile_from_html(html_text)
        self.assertIsNone(u2)
        self.assertEqual(src2, "NOT_FOUND")

    def test_json_changed_structure(self):
        """JSON bị thay đổi cấu trúc hoặc lồng cấp tùy ý."""
        deep_data = {
            "customRoot": {
                "subKey": {
                    "userInfo": {
                        "user": {"id": "999", "uniqueId": "deep_user"},
                        "stats": {"followerCount": 888}
                    }
                }
            }
        }
        u, s2, s, src = find_user_info_struct(deep_data)
        self.assertIsNotNone(u)
        self.assertEqual(u.get("uniqueId"), "deep_user")
        self.assertEqual(s.get("followerCount"), 888)

    def test_invalid_urls(self):
        """URL không hợp lệ hoặc nền tảng không hỗ trợ."""
        empty_res = parse_tiktok_channel_input("")
        self.assertFalse(empty_res.valid)
        self.assertEqual(empty_res.status, "LINK_TRONG")

        yt_res = parse_tiktok_channel_input("https://www.youtube.com/@channel")
        self.assertFalse(yt_res.valid)
        self.assertEqual(yt_res.status, "KHONG_HO_TRO_NEN_TANG")

        space_res = parse_tiktok_channel_input("day la mot chuoi khong hop le")
        self.assertFalse(space_res.valid)
        self.assertEqual(space_res.status, "LINK_TIKTOK_KHONG_HOP_LE")

    def test_duplicate_video_urls_same_creator(self):
        """Nhiều URL video hoặc format khác nhau của cùng 1 creator được deduplicate về 1 kênh."""
        raw_inputs = [
            "https://www.tiktok.com/@kimchungphan20/video/7614484260753345812",
            "https://www.tiktok.com/@kimchungphan20/video/1112223334445556667",
            "https://www.tiktok.com/@kimchungphan20",
            "@kimchungphan20",
            "kimchungphan20",
            "@another_creator",
            "https://www.tiktok.com/@another_creator/video/999999",
        ]

        unique, duplicates = deduplicate_channel_inputs(raw_inputs)
        self.assertEqual(len(unique), 2)
        self.assertEqual(len(duplicates), 5)
        self.assertEqual(unique[0].username, "kimchungphan20")
        self.assertEqual(unique[1].username, "another_creator")

    def test_long_channel_id_as_string(self):
        """ID kênh dài (19 chữ số) phải giữ nguyên dạng string."""
        long_id = "7123456789012345678"
        user = {"id": long_id, "uniqueId": "long_id_user"}
        res = build_profile_result_from_data(
            "long_id_user", "https://www.tiktok.com/@long_id_user", user, None, None, "TEST"
        )
        self.assertEqual(res.user_id, long_id)
        self.assertIsInstance(res.user_id, str)

        # Tránh trường hợp bị cast sang float hoặc int dẫn đến mất số
        d = res.to_dict()
        self.assertIsInstance(d["user_id"], str)
        self.assertEqual(d["user_id"], long_id)

    def test_excel_export_and_reopen(self):
        """Kiểm tra export Excel và mở lại bằng openpyxl."""
        mock_results = [
            TikTokProfileResult(
                input_url="@creator_test",
                profile_url="https://www.tiktok.com/@creator_test",
                username="creator_test",
                nickname="Creator Test",
                user_id="7123456789012345678",
                sec_uid="MS4wLjABAAAAsecuid123",
                bio="Bio line 1\nBio line 2 with =formula_escape",
                follower_count=1500000,
                following_count=30,
                likes_count=20000000,
                video_count=100,
                verified=True,
                private_account=False,
                avatar_url="https://example.com/avatar.jpg",
                bio_website_url="https://shop.example.com",
                collected_at="2026-10-21 15:00:00",
                status="SUCCESS",
                source_method="HTTP/UNIVERSAL_DATA",
                stats_precision="exact",
            ),
            TikTokProfileResult(
                input_url="invalid_channel",
                status="NOT_FOUND",
                error_message="Kênh không tồn tại",
            )
        ]

        file_path = export_profile_excel(
            results=mock_results,
            duplicate_count=1,
            original_count=3,
            elapsed=1.2,
        )

        self.assertTrue(file_path.exists())

        wb = openpyxl.load_workbook(file_path)
        ws = wb.active

        self.assertEqual(ws.title, "Kênh TikTok")
        self.assertEqual(ws.freeze_panes, "A2")
        self.assertIsNotNone(ws.auto_filter.ref)

        # Check Row 2 data
        self.assertEqual(ws.cell(row=2, column=2).value, "creator_test")
        self.assertEqual(ws.cell(row=2, column=4).value, "7123456789012345678")
        self.assertIsInstance(ws.cell(row=2, column=4).value, str)
        self.assertEqual(ws.cell(row=2, column=5).value, 1500000)
        self.assertIsInstance(ws.cell(row=2, column=5).value, int)
        self.assertEqual(ws.cell(row=2, column=9).value, "Có")
        self.assertEqual(ws.cell(row=2, column=10).value, "Không")

        # Check Formula Sanitization: '=formula_escape' became "'=formula_escape"
        bio_val = ws.cell(row=2, column=11).value
        self.assertIn("Bio line 1", bio_val)

        # Check Row 3 data (NOT_FOUND)
        self.assertEqual(ws.cell(row=3, column=14).value, "Không tìm thấy kênh")

    def test_no_cross_account_leak_in_sigi_state(self):
        """Đảm bảo không lấy nhầm user khác khi UserModule có nhiều user."""
        data = {
            "UserModule": {
                "users": {
                    "logged_in_user": {
                        "id": "111111",
                        "uniqueId": "logged_in_user",
                        "nickname": "Current Logged In User",
                    },
                    "target_creator": {
                        "id": "222222",
                        "uniqueId": "target_creator",
                        "nickname": "Target Creator",
                    },
                },
                "stats": {
                    "logged_in_user": {
                        "followerCount": 10,
                        "heartCount": 5,
                    },
                    "target_creator": {
                        "followerCount": 999999,
                        "heartCount": 888888,
                    },
                },
            }
        }
        # Khi tìm target_creator, phải trả về target_creator chứ KHÔNG PHẢI logged_in_user
        u, s2, s, src = find_user_info_struct(data, expected_username="target_creator")
        self.assertIsNotNone(u)
        self.assertEqual(u.get("uniqueId"), "target_creator")
        self.assertEqual(s.get("followerCount"), 999999)

        # Khi tìm một username không có trong users, không được lấy đại user đầu tiên
        u_none, _, _, _ = find_user_info_struct(data, expected_username="unknown_user")
        self.assertIsNone(u_none)

    def test_digg_count_not_used_as_channel_likes(self):
        """Tuyệt đối không lấy diggCount (video đã thích) làm likes của kênh."""
        user_node = {
            "id": "12345",
            "uniqueId": "test_creator",
            "nickname": "Test Creator",
        }
        stats_node = {
            "followerCount": 100,
            "followingCount": 50,
            "diggCount": 789,  # Video creator đã thích
            "videoCount": 20,
            # heartCount thiếu
        }
        res = build_profile_result_from_data(
            input_url="@test_creator",
            normalized_url="https://www.tiktok.com/@test_creator",
            user_node=user_node,
            stats_v2=None,
            stats_node=stats_node,
            source_method="HTTP/TEST",
            target_username="test_creator",
        )
        self.assertEqual(res.follower_count, 100)
        # Likes phải là None vì heartCount thiếu, KHÔNG được bằng 789 (diggCount)
        self.assertIsNone(res.likes_count)

    def test_formula_injection_prevention(self):
        """Ký tự nguy hiểm =, +, -, @ ở đầu chuỗi text được prefix dấu nháy đơn."""
        from app.utils.profile_excel import sanitize_text
        self.assertEqual(sanitize_text("=SUM(A1:A10)"), "'=SUM(A1:A10)")
        self.assertEqual(sanitize_text("+cmd|' /C calc'!A0"), "'+cmd|' /C calc'!A0")
        self.assertEqual(sanitize_text("-5+2"), "'-5+2")
        self.assertEqual(sanitize_text("@SUM"), "'@SUM")
        self.assertEqual(sanitize_text("Normal Text"), "Normal Text")
        self.assertEqual(sanitize_text(12345), 12345)

    def test_video_performance_regression(self):
        """Đảm bảo tính năng phân tích video hiện tại không bị ảnh hưởng."""
        video_url = "https://www.tiktok.com/@kimchungphan20/video/7614484260753345812"
        parsed = parse_tiktok_url(video_url)
        self.assertTrue(parsed.valid)
        self.assertEqual(parsed.username, "kimchungphan20")
        self.assertEqual(parsed.video_id, "7614484260753345812")

        urls = [
            video_url,
            video_url,
            "https://www.tiktok.com/@other/video/1234567890123456789",
        ]
        unique_urls, dups = deduplicate_urls(urls)
        self.assertEqual(len(unique_urls), 2)
        self.assertEqual(len(dups), 1)

        v_res = VideoResult(
            link=video_url,
            view=1000,
            like=100,
            comment=10,
            share=5,
            save=2,
            status="THANH_CONG",
        )
        self.assertEqual(v_res.view, 1000)
        self.assertEqual(v_res.to_dict()["status"], "THANH_CONG")


if __name__ == "__main__":
    unittest.main()
