import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "../../services/apiClient";
import "./readerExtras.css";

export interface RecentProgress {
  novel_id: number;
  novel_title: string;
  library_id: number;
  chapter_number: number | null;
  position: number;
  percent: number;
  updated_at: string;
}

/** Home row of the most recently read stories; one tap reopens the reader at the saved chapter. */
const ContinueReading: React.FC<{ limit?: number }> = ({ limit = 8 }) => {
  const navigate = useNavigate();
  const [items, setItems] = useState<RecentProgress[]>([]);

  useEffect(() => {
    let cancelled = false;
    apiClient.get<RecentProgress[]>("/chapter/progress/recent", { params: { limit } })
      .then((response) => {
        if (!cancelled && Array.isArray(response.data)) {
          setItems(response.data.filter((item) => item.chapter_number !== null));
        }
      })
      .catch(() => { if (!cancelled) setItems([]); });
    return () => { cancelled = true; };
  }, [limit]);

  if (items.length === 0) return null;

  return (
    <section className="continue-reading" aria-label="Continue reading">
      <h2>Continue reading</h2>
      <div className="continue-reading__row">
        {items.map((item) => (
          <button
            key={`${item.novel_id}-${item.chapter_number}`}
            type="button"
            className="continue-reading__card"
            onClick={() => navigate(`/library/${item.library_id}/novels/${item.novel_id}/${item.chapter_number}`)}
          >
            <strong>{item.novel_title}</strong>
            <span>Chapter {item.chapter_number} · {Math.round(item.percent)}%</span>
          </button>
        ))}
      </div>
    </section>
  );
};

export default ContinueReading;
