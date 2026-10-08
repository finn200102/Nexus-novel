import React from "react";
import HiddenContentPanel from "../components/organization/HiddenContentPanel";
import "../styles/organization.css";

const HiddenContentPage: React.FC = () => (
  <div className="integrations-page">
    <header className="integrations-page__header">
      <div>
        <p className="library-workspace__eyebrow">Your account</p>
        <h1>Hidden content</h1>
        <p>Tags, fandoms, genres, authors and words you never want to see in discovery.</p>
      </div>
    </header>
    <HiddenContentPanel />
  </div>
);

export default HiddenContentPage;
