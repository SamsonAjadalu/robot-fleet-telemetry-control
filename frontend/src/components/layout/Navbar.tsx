import React from 'react';
import { Link } from 'react-router-dom';

const Navbar: React.FC = () => (
    <nav>
        <div className="nav-container">
            <Link to="/" id="nav-logo-text">Robot Fleet Telemetry &amp; Control</Link>
            <input className="menu-btn" type="checkbox" id="menu-btn" />
            <label className="menu-icon" htmlFor="menu-btn"><span className="navicon"></span></label>
            <ul className="menu">
                <li><Link to="/">Dashboard</Link></li>
                <li><Link to="/fleet-summary">Stored fleet</Link></li>
            </ul>
        </div>
    </nav>
);

export default Navbar;
