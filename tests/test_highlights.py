import unittest

from shorts_generator.highlights import _sanitize_highlights, get_highlights

SEGMENTS = [{"start": float(i), "end": float(i + 10), "text": f"Thought {i}."} for i in range(0, 100, 10)]


class LongVideoChunkingTests(unittest.TestCase):
    def test_excessively_long_output_is_reduced_at_sentence_boundary(self):
        result = _sanitize_highlights(
            [{"title": "long", "start_time": 0, "end_time": 95, "score": 90}],
            duration=100,
            segments=SEGMENTS,
        )

        self.assertEqual(0.0, result[0]["start_time"])
        self.assertEqual(40.0, result[0]["end_time"])

    def test_excessively_short_output_is_expanded_at_sentence_boundary(self):
        result = _sanitize_highlights(
            [{"title": "short", "start_time": 10, "end_time": 14, "score": 90}],
            duration=100,
            segments=SEGMENTS,
        )

        self.assertEqual(10.0, result[0]["start_time"])
        self.assertEqual(50.0, result[0]["end_time"])

    def test_second_chunk_uses_relative_times_and_returns_global_times(self):
        transcript = {
            "duration": 1801.0,
            "segments": SEGMENTS
            + [{**s, "start": s["start"] + 1140, "end": s["end"] + 1140} for s in SEGMENTS]
            + [{"start": 1790.0, "end": 1801.0, "text": "ending."}],
        }
        prompts = []

        def fake_llm(prompt):
            prompts.append(prompt)
            if len(prompts) == 1:
                return '{"content_type":"podcast","density":"medium"}'
            if len(prompts) == 2:
                return '{"highlights":[{"title":"first","start_time":10,"end_time":50,"score":80}]}'
            return '{"highlights":[{"title":"second","start_time":10,"end_time":14,"score":90}]}'

        result = get_highlights(transcript, num_clips=1, llm_fn=fake_llm)

        self.assertIn("[10.0s] Thought 10.", prompts[2])
        self.assertNotIn("[1150.0s]", prompts[2])
        second = next(h for h in result["highlights"] if h["title"] == "second")
        self.assertEqual(1150.0, second["start_time"])
        self.assertEqual(1190.0, second["end_time"])
        self.assertEqual(40.0, second["end_time"] - second["start_time"])


if __name__ == "__main__":
    unittest.main()
