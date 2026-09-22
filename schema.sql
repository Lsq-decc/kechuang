CREATE DATABASE IF NOT EXISTS kechuang
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE kechuang;

CREATE TABLE IF NOT EXISTS users (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    username VARCHAR(50) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(50) NOT NULL,
    student_id VARCHAR(50) NULL,
    department VARCHAR(100) NOT NULL DEFAULT '未设置',
    role VARCHAR(20) NOT NULL DEFAULT 'member',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_username (username),
    UNIQUE KEY uq_users_student_id (student_id),
    KEY ix_users_role (role),
    KEY ix_users_name (name),
    CONSTRAINT chk_users_role CHECK (role IN ('member', 'leader', 'admin'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS schedule_uploads (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    stored_filename VARCHAR(255) NOT NULL,
    image_path VARCHAR(500) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    ocr_text TEXT NULL,
    ocr_result JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_uploads_stored_filename (stored_filename),
    KEY ix_uploads_user_id (user_id),
    KEY ix_uploads_status (status),
    CONSTRAINT fk_uploads_user
        FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT chk_uploads_status CHECK (status IN ('pending', 'confirmed', 'failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS courses (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    upload_id INT UNSIGNED NULL,
    weekday TINYINT UNSIGNED NOT NULL,
    start_period TINYINT UNSIGNED NOT NULL,
    end_period TINYINT UNSIGNED NOT NULL,
    course_name VARCHAR(150) NOT NULL,
    weeks VARCHAR(255) NOT NULL DEFAULT '',
    location VARCHAR(150) NOT NULL DEFAULT '',
    note VARCHAR(255) NOT NULL DEFAULT '',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_courses_user_id (user_id),
    KEY ix_courses_upload_id (upload_id),
    KEY ix_courses_time_lookup (weekday, start_period, end_period),
    CONSTRAINT fk_courses_user
        FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT fk_courses_upload
        FOREIGN KEY (upload_id) REFERENCES schedule_uploads (id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,
    CONSTRAINT chk_courses_weekday CHECK (weekday BETWEEN 1 AND 7),
    CONSTRAINT chk_courses_start_period CHECK (start_period BETWEEN 1 AND 12),
    CONSTRAINT chk_courses_end_period CHECK (end_period BETWEEN 1 AND 12),
    CONSTRAINT chk_courses_period_order CHECK (start_period <= end_period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS query_logs (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    operator_id INT UNSIGNED NULL,
    weekday TINYINT UNSIGNED NOT NULL,
    start_period TINYINT UNSIGNED NOT NULL,
    end_period TINYINT UNSIGNED NOT NULL,
    week_number TINYINT UNSIGNED NULL,
    department VARCHAR(100) NOT NULL DEFAULT '',
    result_count INT UNSIGNED NOT NULL DEFAULT 0,
    criteria JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_query_logs_operator_id (operator_id),
    KEY ix_query_logs_created_at (created_at),
    CONSTRAINT fk_query_logs_operator
        FOREIGN KEY (operator_id) REFERENCES users (id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,
    CONSTRAINT chk_query_logs_weekday CHECK (weekday BETWEEN 1 AND 7),
    CONSTRAINT chk_query_logs_periods CHECK (
        start_period BETWEEN 1 AND 12
        AND end_period BETWEEN 1 AND 12
        AND start_period <= end_period
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS availability_overrides (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    week_number TINYINT UNSIGNED NOT NULL,
    weekday TINYINT UNSIGNED NOT NULL,
    start_period TINYINT UNSIGNED NOT NULL,
    end_period TINYINT UNSIGNED NOT NULL,
    is_free BOOLEAN NOT NULL DEFAULT TRUE,
    note VARCHAR(255) NOT NULL DEFAULT '',
    created_by_id INT UNSIGNED NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_availability_override_slot (
        user_id,
        week_number,
        weekday,
        start_period,
        end_period
    ),
    KEY ix_availability_override_lookup (
        week_number,
        weekday,
        start_period,
        end_period
    ),
    KEY ix_availability_overrides_user_id (user_id),
    KEY ix_availability_overrides_created_by_id (created_by_id),
    CONSTRAINT fk_availability_overrides_user
        FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT fk_availability_overrides_created_by
        FOREIGN KEY (created_by_id) REFERENCES users (id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,
    CONSTRAINT chk_availability_overrides_week
        CHECK (week_number BETWEEN 1 AND 30),
    CONSTRAINT chk_availability_overrides_weekday
        CHECK (weekday BETWEEN 1 AND 7),
    CONSTRAINT chk_availability_overrides_periods CHECK (
        start_period BETWEEN 1 AND 12
        AND end_period BETWEEN 1 AND 12
        AND start_period <= end_period
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS material_folders (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    department VARCHAR(100) NOT NULL,
    name VARCHAR(100) NOT NULL,
    parent_id INT UNSIGNED NULL,
    created_by_id INT UNSIGNED NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_material_folder_name (department, parent_id, name),
    KEY ix_material_folders_department (department),
    KEY ix_material_folders_parent (department, parent_id),
    KEY ix_material_folders_created_by_id (created_by_id),
    CONSTRAINT fk_material_folders_parent
        FOREIGN KEY (parent_id) REFERENCES material_folders (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT fk_material_folders_created_by
        FOREIGN KEY (created_by_id) REFERENCES users (id)
        ON DELETE SET NULL
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS material_files (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    department VARCHAR(100) NOT NULL,
    folder_id INT UNSIGNED NULL,
    original_filename VARCHAR(255) NOT NULL,
    storage_key VARCHAR(500) NOT NULL,
    content_type VARCHAR(150) NOT NULL DEFAULT '',
    file_size BIGINT NOT NULL DEFAULT 0,
    created_by_id INT UNSIGNED NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_material_files_storage_key (storage_key),
    KEY ix_material_files_department (department),
    KEY ix_material_files_folder (department, folder_id),
    KEY ix_material_files_created_by_id (created_by_id),
    CONSTRAINT fk_material_files_folder
        FOREIGN KEY (folder_id) REFERENCES material_folders (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT fk_material_files_created_by
        FOREIGN KEY (created_by_id) REFERENCES users (id)
        ON DELETE SET NULL
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS todo_items (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    title VARCHAR(200) NOT NULL,
    note VARCHAR(500) NOT NULL DEFAULT '',
    priority VARCHAR(10) NOT NULL DEFAULT 'medium',
    is_completed BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_todo_items_user_id (user_id),
    KEY ix_todo_items_user_status (user_id, is_completed),
    KEY ix_todo_items_user_priority (user_id, priority),
    KEY ix_todo_items_priority (priority),
    KEY ix_todo_items_is_completed (is_completed),
    CONSTRAINT fk_todo_items_user
        FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT chk_todo_items_priority
        CHECK (priority IN ('high', 'medium', 'low'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
